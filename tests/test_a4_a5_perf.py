"""A4 + A5 性能小改测试。

A4：``_resolve_outline_source`` 单次目录扫描（替代原 3 次扫描）。
A5：``_detect_angle_projection`` 大图先 downsample 到 short 边 = 1000。
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from book_cut.pipeline import _first_and_count_pdfs, _resolve_outline_source
from book_cut.preprocess.deskew import _detect_angle_projection

# ============ A4 测试 ============


def test_a4_single_pdf_returns_immediately():
    """A4：单 PDF 文件 → 立即返回，不扫目录。"""
    single = Path("samples/ZHSY100456_醉翁琴趣外篇_宋歐陽修撰_清初影宋抄本.pdf")
    src, is_multi = _resolve_outline_source(single)
    assert src == single
    assert is_multi is False


def test_a4_empty_folder_returns_none(tmp_path):
    """A4：空目录 → (None, False)。"""
    src, is_multi = _resolve_outline_source(tmp_path)
    assert src is None
    assert is_multi is False


def test_a4_folder_with_pdfs_returns_first_and_count():
    """A4：含 PDF 的目录 → (first_pdf, True) 多 PDF 标志。"""
    folder = Path("samples")
    src, is_multi = _resolve_outline_source(folder)
    assert src is not None
    assert src.suffix.lower() == ".pdf"
    assert is_multi is True  # samples/ 有多个 PDF


def test_a4_first_and_count_pdfs_single_match(tmp_path):
    """A4：``_first_and_count_pdfs`` 单 PDF → count=1。"""
    # 创建临时 PDF 文件
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n%fake")
    first, count = _first_and_count_pdfs(tmp_path)
    assert first is not None
    assert first.name == "a.pdf"
    assert count == 1


def test_a4_first_and_count_pdfs_case_insensitive(tmp_path):
    """A4：大写扩展名 .PDF 也算 PDF。"""
    (tmp_path / "lower.pdf").write_bytes(b"%PDF-1.4\n%fake")
    (tmp_path / "UPPER.PDF").write_bytes(b"%PDF-1.4\n%fake")
    first, count = _first_and_count_pdfs(tmp_path)
    assert count == 2
    # first 按文件名排序
    assert first.name == "UPPER.PDF"


def test_a4_first_and_count_pdfs_nested(tmp_path):
    """A4：递归查找子目录 PDF。"""
    (tmp_path / "subdir").mkdir()
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n%fake")
    (tmp_path / "subdir" / "b.pdf").write_bytes(b"%PDF-1.4\n%fake")
    first, count = _first_and_count_pdfs(tmp_path)
    assert count == 2
    assert first is not None


def test_a4_first_and_count_pdfs_empty(tmp_path):
    """A4：空目录 → (None, 0)。"""
    first, count = _first_and_count_pdfs(tmp_path)
    assert first is None
    assert count == 0


# ============ A5 测试 ============


def _make_tilted_page(h: int = 1000, w: int = 1000, angle: float = 2.0) -> np.ndarray:
    """合成一张倾斜的"文字页"：白底 + 横向文本线。"""
    import cv2

    gray = np.full((h, w), 240, dtype=np.uint8)
    for y in range(100, h - 100, 50):
        gray[y:y + 5, 200:w - 200] = 30
    # 倾斜
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h), borderValue=255)


def test_a5_detects_correct_angle_with_downsample():
    """A5：1000×1000 不缩（short 边 ≤ downsample）→ 角度检测正确。"""
    gray = _make_tilted_page(1000, 1000, angle=2.0)
    detected = _detect_angle_projection(gray, max_angle=5.0, downsample=1000)
    # 反向符号：detected 是图像坐标下"线相对水平"角度，需要反向旋转才能回正
    # 实际：我们合成时旋转 +2°，warpAffine 角度检测会找到 -2°
    assert detected is not None
    assert abs(detected - (-2.0)) < 0.3, f"detected={detected}, expected -2.0"


def test_a5_downsamples_large_image():
    """A5：4000×4000 → 缩到 1000×1000 后角度检测仍正确。"""
    gray = _make_tilted_page(4000, 4000, angle=2.0)
    detected = _detect_angle_projection(gray, max_angle=5.0, downsample=1000)
    assert detected is not None
    assert abs(detected - (-2.0)) < 0.5, f"detected={detected}, expected -2.0 (downsample 仍准)"


def test_a5_downsample_smaller_size_faster():
    """A5：4000×4000 downsample=1000 比不缩明显快。

    阈值 1.5×（实测 ~9×，留余量给环境噪声）。
    """
    gray = _make_tilted_page(4000, 4000, angle=0.0)
    # 用 downsample=10000（等价"不缩"或缩后比原图大）
    t_old = time.perf_counter()
    for _ in range(2):
        _detect_angle_projection(gray, max_angle=5.0, downsample=10000)
    elapsed_old = (time.perf_counter() - t_old) / 2

    # 用 downsample=1000（缩到 1000²）
    t_new = time.perf_counter()
    for _ in range(2):
        _detect_angle_projection(gray, max_angle=5.0, downsample=1000)
    elapsed_new = (time.perf_counter() - t_new) / 2

    # downsample 应该显著更快（实测 ~9×，阈值放宽到 1.5×）
    assert elapsed_new < elapsed_old * 0.7, (
        f"downsample 没加速: old={elapsed_old*1000:.1f}ms, new={elapsed_new*1000:.1f}ms"
    )


def test_a5_downsample_zero_disables():
    """A5：``downsample=0`` → 不缩（保留 v1.5 行为）。"""
    gray = _make_tilted_page(1000, 1000, angle=2.0)
    # downsample=0 应该禁用降采样（max(h, w) > 0 不成立）
    detected = _detect_angle_projection(gray, max_angle=5.0, downsample=0)
    assert detected is not None
    assert abs(detected - (-2.0)) < 0.3


def test_a5_no_tilt_returns_near_zero():
    """A5：无倾斜页 → 检测角度接近 0。"""
    gray = _make_tilted_page(1000, 1000, angle=0.0)
    detected = _detect_angle_projection(gray, max_angle=5.0, downsample=1000)
    assert detected is not None
    assert abs(detected) < 0.5, f"无倾斜页应检测到 ~0°，实际 {detected}"


# ============ 集成测试：端到端不破坏 ============


def test_a4_a5_pipeline_still_runs(tmp_path):
    """A4+A5 改动不影响 pipeline 端到端。"""
    import argparse
    from io import BytesIO

    import pymupdf
    from PIL import Image

    # 合成 2 页 PDF
    pngs = []
    for _ in range(2):
        arr = np.full((300, 400), 240, dtype=np.uint8)
        arr[100:105, 150:155] = 30
        img = Image.fromarray(arr, mode="L")
        buf = BytesIO()
        img.save(buf, format="PNG")
        pngs.append(buf.getvalue())

    doc = pymupdf.open()
    for png in pngs:
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, stream=png)
    in_pdf = tmp_path / "in.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf), output=str(out_dir),
        split="half", crop="trim", binarize="none",
        deskew=False, auto_single_page=True, page_order="ltr", outline=True,
        format="png", crop_adaptive="auto", paper_pages=2, paper_deviation=30,
        half_offset=0, no_morph=False, pdf=False,
    )

    from book_cut.pipeline import run_pipeline
    run_pipeline(args)
    out_files = sorted(out_dir.glob("*.png"))
    # 2 pages × 2 (half) = 4
    assert len(out_files) == 4
