"""边界用例测试（D2：v1.5 Sprint 1 防回归）。

覆盖：
- 空文件夹：pipeline 优雅退出（warn + return）—— 等价于 0 页 PDF
- 损坏 PDF：明确错误（不静默吞掉）
- 非标尺寸：3708×3862 / 4288×3330（真实扫描件尺寸）
- ``--paper-pages 0``：兜底默认 paper_color=240
- ``--paper-pages > total pages``：clamp 到实际页数
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from book_cut.pipeline import run_pipeline


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def _make_double_page_png_bytes(size: tuple[int, int] = (800, 500)) -> bytes:
    """合成一张双页 PNG（左/右各黑块 + 中间白缝）。"""
    w, h = size
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    for y in range(50, h - 50, 40):
        draw.rectangle([(50, y), (w // 2 - 50, y + 20)], fill="black")
        draw.rectangle([(w // 2 + 50, y), (w - 50, y + 20)], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_args(
    input_path: Path,
    output_dir: Path,
    **overrides,
) -> argparse.Namespace:
    """构造 run_pipeline 用的最小 Namespace。"""
    base = dict(
        input=str(input_path),
        output=str(output_dir),
        split="half",  # 默认用最稳的 half 切分
        crop="none",
        binarize="none",
        deskew=False,
        auto_single_page=True,
        page_order="ltr",
        outline=True,
        format="png",
        crop_adaptive="auto",
        paper_pages=5,
        half_offset=0,
        pdf=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ----------------------------------------------------------------------------
# T1：空文件夹 → 优雅退出（pymupdf 不允许保存 0 页 PDF，所以用空文件夹代理）
# ----------------------------------------------------------------------------


# ----------------------------------------------------------------------------
# T2：损坏 PDF → 明确错误（不静默）
# ----------------------------------------------------------------------------


def test_corrupted_pdf_raises_clear_error(tmp_path: Path) -> None:
    """损坏 PDF（garbage bytes）→ pymupdf 抛错，pipeline 透传。

    重要：不能静默吞掉，否则用户拿到空输出目录却以为成功了。
    """
    # 写一个 .pdf 后缀但内容是 garbage
    bad = tmp_path / "garbage.pdf"
    bad.write_bytes(b"this is not a real PDF, just some random bytes" * 10)

    out_dir = tmp_path / "out"
    args = _make_args(bad, out_dir)

    # pymupdf 会抛 FileDataError 或类似 → 透传
    with pytest.raises(Exception) as exc_info:
        run_pipeline(args)

    # 错误消息应能让人识别（不强制 pymupdf 字面，只验证非空）
    assert str(exc_info.value), "错误消息不应为空"


# ----------------------------------------------------------------------------
# T3：非标尺寸（真实扫描件）
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [
        (3708, 3862),  # memory 提过的真实扫描件 #1
        (4288, 3330),  # memory 提过的真实扫描件 #2
        (3000, 4000),  # 接近 4000x4000 基准
    ],
)
def test_nonstandard_size_runs_cleanly(tmp_path: Path, size: tuple[int, int]) -> None:
    """非标尺寸 PDF：pipeline 不崩，输出页数 = 输入页数 × 2（half 切分）。

    历史上真实古籍扫描件不是 4000x4000 标准正方形，pipeline 必须能 handle。
    """
    import pymupdf

    w, h = size
    png_bytes = _make_double_page_png_bytes(size=(min(w, 800), min(h, 500)))  # 实际图小一些
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=w, height=h)
        page.insert_image(page.rect, stream=png_bytes)
    in_pdf = tmp_path / "nonstd.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = _make_args(in_pdf, out_dir, split="half")

    run_pipeline(args)

    # half 切分：2 页 × 2 = 4 张输出
    out_files = sorted(out_dir.glob("*.png"))
    assert len(out_files) == 4, f"非标尺寸应输出 4 张，实际 {len(out_files)}"


# ----------------------------------------------------------------------------
# T4：--paper-pages 0 → 兜底默认 paper_color=240
# ----------------------------------------------------------------------------


def test_paper_pages_zero_uses_default_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--paper-pages 0``：不走采样，直接用 default paper_color=240。

    验证：_build_crop_config 走 "no samples" 分支。
    副作用：不应打印 "sampled N pages"（因为 paper_pages=0 短路）。
    """
    import pymupdf

    png_bytes = _make_double_page_png_bytes()
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    in_pdf = tmp_path / "p0.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = _make_args(in_pdf, out_dir, crop="trim", paper_pages=0)

    run_pipeline(args)

    captured = capsys.readouterr()
    # paper_pages=0 → "自适应裁切: ..." 这行不应出现
    assert "自适应裁切" not in captured.out, (
        f"--paper-pages 0 不应打印采样信息，实际：\n{captured.out}"
    )

    # 仍应正常产出（half 切分：3 页 × 2 = 6 张）
    out_files = sorted(out_dir.glob("*.png"))
    assert len(out_files) == 6


# ----------------------------------------------------------------------------
# T5：--paper-pages > total pages → clamp 到实际页数
# ----------------------------------------------------------------------------


def test_paper_pages_clamped_to_actual(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--paper-pages 100`` 但 PDF 只有 3 页 → 只采样 3 页，不报错。

    验证：slicing `pages[:100]` 安全（< 实际长度），且日志显示真实采样数。
    """
    import pymupdf

    png_bytes = _make_double_page_png_bytes()
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    in_pdf = tmp_path / "short.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = _make_args(in_pdf, out_dir, crop="trim", paper_pages=100)

    run_pipeline(args)  # 不应抛 IndexError 或类似

    captured = capsys.readouterr()
    # 采样信息应显示真实采样数 3（不是 100）
    assert "sampled 3 pages" in captured.out, (
        f"--paper-pages 100 应采样 3 页（被 clamp），实际：\n{captured.out}"
    )

    out_files = sorted(out_dir.glob("*.png"))
    # half 切分：3 页 × 2 = 6 张
    assert len(out_files) == 6


# ----------------------------------------------------------------------------
# T6（额外）：空文件夹
# ----------------------------------------------------------------------------


def test_empty_folder_returns_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """空文件夹输入：同 0 页 PDF 行为。"""
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    out_dir = tmp_path / "out"
    args = _make_args(empty_folder, out_dir)

    run_pipeline(args)

    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert not list(out_dir.iterdir())