"""v1.8 dry-run 预览模式测试。

覆盖：
- 拼图渲染（render_compare）：3 列 / 2 列 / 大小限制
- 指标汇总（compute_summary）：schema 完整性
- 写盘（write_preview）：文件生成 / 文件夹创建
- CLI 互斥：--dry-run + --pdf / --sample-n < 1 错误
- 端到端：单图 / 多页 PDF 走 dry-run 不写 image
- 写盘隔离：dry-run 不创建 output 目录
- 性能：3 页 ≤ 5s（宽松阈值）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

# 让 subprocess 能找到 book_cut 模块
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_ENV = {**os.environ, "PYTHONPATH": str(_SRC)}


# ----------------------------------------------------------------------------
# preview.py 单元测试
# ----------------------------------------------------------------------------


def test_render_compare_3_columns():
    """3 列（原图 | L | R）拼图大小合理。"""
    from book_cut.pipeline.preview import render_compare

    original = Image.new("RGB", (400, 300), "white")
    left = Image.new("RGB", (200, 300), "white")
    right = Image.new("RGB", (200, 300), "white")
    meta = {
        "source": "test.pdf",
        "page_idx": 0,
        "split_x": 400,
        "size_in": [800, 300],
    }
    out = render_compare(original, left, right, meta)
    assert out.size[0] <= 6000
    assert out.size[1] <= 3000
    assert out.size[0] > 0 and out.size[1] > 0


def test_render_compare_single_page():
    """单页（无 R 列）：仅 2 列。"""
    from book_cut.pipeline.preview import render_compare

    original = Image.new("RGB", (400, 300), "white")
    meta = {"source": "single.jpg", "page_idx": 0, "split_x": None, "size_in": [400, 300]}
    out = render_compare(original, None, None, meta)
    # 单页时只渲染 1 张图 + 标题
    assert out.size[0] > 0


def test_render_compare_max_width_enforced():
    """超宽输入：总宽限制 ≤ 6000px。"""
    from book_cut.pipeline.preview import render_compare

    original = Image.new("RGB", (8000, 4000), "white")
    left = Image.new("RGB", (4000, 4000), "white")
    right = Image.new("RGB", (4000, 4000), "white")
    meta = {"source": "huge.pdf", "page_idx": 0, "split_x": 8000, "size_in": [8000, 4000]}
    out = render_compare(original, left, right, meta)
    assert out.size[0] <= 6000


def test_compute_summary_schema():
    """summary 必填字段齐全。"""
    from book_cut.pipeline.preview import compute_summary

    summary = compute_summary(
        input_path="book.pdf",
        config={"split": "gutter", "crop": "border", "binarize": "sauvola", "deskew": True, "page_order": "ltr"},
        sample_indices=[0, 1, 2],
        total_pages=130,
        pages_metrics=[
            {"page_idx": 0, "split": {"confidence": 0.8}, "warnings": []},
            {"page_idx": 1, "split": {"confidence": 0.3}, "warnings": ["low_conf"]},
            {"page_idx": 2, "split": {"confidence": 0.9}, "warnings": []},
        ],
        elapsed_ms={"total": 482, "per_page_avg": 161, "estimated_full": 20930},
        paper_color=218,
    )
    assert summary["tool"] == "book-cut"
    assert summary["version"] == "1.8.0"
    assert summary["mode"] == "dry-run"
    assert summary["input"]["total_pages"] == 130
    assert summary["input"]["sampled_pages"] == 3
    assert summary["input"]["sample_indices"] == [0, 1, 2]
    assert summary["config"]["split"] == "gutter"
    assert summary["elapsed_ms"]["per_page_avg"] == 161
    assert summary["paper_color_estimate"] == 218
    assert summary["pages_with_warnings"] == [1]  # idx 1 有 warning
    assert "建议" in summary["suggestion"] or "confidence" in summary["suggestion"]


def test_write_preview_creates_files(tmp_path: Path):
    """write_preview 写出 compare PNG + summary JSON + README。"""
    from book_cut.pipeline.preview import write_preview

    preview_dir = tmp_path / "preview"
    compare = Image.new("RGB", (1000, 500), "white")
    pages_metrics = [{"page_idx": 0, "split": {"x": 400, "confidence": 0.8}}]
    summary = {"tool": "book-cut", "version": "1.8.0", "input": {"path": "test.pdf"}}

    write_preview(preview_dir, [(0, compare)], pages_metrics, summary)

    assert preview_dir.exists()
    assert (preview_dir / "preview_p0001_compare.png").exists()
    assert (preview_dir / "preview_summary.json").exists()
    assert (preview_dir / "README.txt").exists()
    # JSON 合法
    loaded = json.loads((preview_dir / "preview_summary.json").read_text(encoding="utf-8"))
    assert loaded["tool"] == "book-cut"
    assert len(loaded["pages"]) == 1


# ----------------------------------------------------------------------------
# orchestrator dry-run 端到端
# ----------------------------------------------------------------------------


def test_dry_run_creates_no_output_dir(tmp_path: Path, two_page_image: Image.Image):
    """dry-run 模式：output 目录不应被创建。"""
    from book_cut.pipeline.orchestrator import run_pipeline

    input_img = tmp_path / "test.png"
    two_page_image.save(input_img)
    output_dir = tmp_path / "out"
    assert not output_dir.exists()  # 提前确认不存在

    args = argparse.Namespace(
        input=str(input_img),
        output=str(output_dir),
        split="gutter",
        crop="none",
        binarize="none",
        deskew=False,
        format="png",
        pdf=False,
        page_order="ltr",
        outline=True,
        no_morph=False,
        pdf_page_size="keep",
        paper_pages=3,
        paper_deviation=30,
        dry_run=True,
        sample_n=1,
        preview_output=str(tmp_path / "preview"),
    )
    run_pipeline(args)

    # dry-run 后 output 目录仍不存在
    assert not output_dir.exists()
    # 但 preview 目录被创建
    assert (tmp_path / "preview").exists()


def test_dry_run_produces_compare_png_and_summary(tmp_path: Path, two_page_image: Image.Image):
    """dry-run 输出：preview_p*_compare.png + preview_summary.json。"""
    from book_cut.pipeline.orchestrator import run_pipeline

    input_img = tmp_path / "test.png"
    two_page_image.save(input_img)
    preview = tmp_path / "preview"

    args = argparse.Namespace(
        input=str(input_img),
        output=str(tmp_path / "out"),
        split="gutter",
        crop="border",
        binarize="sauvola",
        deskew=True,
        format="png",
        pdf=False,
        page_order="ltr",
        outline=True,
        no_morph=False,
        pdf_page_size="keep",
        paper_pages=3,
        paper_deviation=30,
        dry_run=True,
        sample_n=1,
        preview_output=str(preview),
    )
    run_pipeline(args)

    pngs = list(preview.glob("preview_p*_compare.png"))
    assert len(pngs) == 1
    summary = json.loads((preview / "preview_summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "dry-run"
    assert summary["input"]["sampled_pages"] == 1
    assert summary["config"]["split"] == "gutter"
    assert summary["config"]["binarize"] == "sauvola"


def test_dry_run_with_synthetic_pdf(synthetic_pdf_with_outline: Path, tmp_path: Path):
    """dry-run 用 5 页 PDF 走通：3 个 compare PNG + summary。"""
    from book_cut.pipeline.orchestrator import run_pipeline

    preview = tmp_path / "preview"
    args = argparse.Namespace(
        input=str(synthetic_pdf_with_outline),
        output=str(tmp_path / "out"),
        split="gutter",
        crop="border",
        binarize="none",
        deskew=False,
        format="png",
        pdf=False,
        page_order="ltr",
        outline=True,
        no_morph=False,
        pdf_page_size="keep",
        paper_pages=3,
        paper_deviation=30,
        dry_run=True,
        sample_n=3,
        preview_output=str(preview),
    )
    run_pipeline(args)

    pngs = sorted(preview.glob("preview_p*_compare.png"))
    assert len(pngs) == 3
    summary = json.loads((preview / "preview_summary.json").read_text(encoding="utf-8"))
    assert summary["input"]["sampled_pages"] == 3
    assert summary["input"]["sample_indices"] == [0, 1, 2]
    # 每页都有 split metrics
    assert len(summary["pages"]) == 3
    for p in summary["pages"]:
        assert "split" in p
        assert "confidence" in p["split"]


# ----------------------------------------------------------------------------
# CLI 互斥校验
# ----------------------------------------------------------------------------


def test_cli_dry_run_with_pdf_warns(tmp_path: Path, two_page_image: Image.Image, capsys):
    """``--dry-run --pdf`` → 退出码 0，stderr/stdout 包含 warn。"""
    input_img = tmp_path / "test.png"
    two_page_image.save(input_img)

    result = subprocess.run(
        [
            sys.executable, "-m", "book_cut.cli",
            "-i", str(input_img),
            "-o", str(tmp_path / "out"),
            "--dry-run",
            "--sample-n", "1",
            "--preview-output", str(tmp_path / "preview"),
            "--pdf",  # 应被 warn
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=_ENV,
    )
    assert result.returncode == 0
    assert "忽略 --pdf" in result.stdout or "忽略 --pdf" in result.stderr


def test_cli_sample_n_zero_errors(tmp_path: Path, two_page_image: Image.Image):
    """``--sample-n 0`` → 退出码非 0。"""
    input_img = tmp_path / "test.png"
    two_page_image.save(input_img)

    result = subprocess.run(
        [
            sys.executable, "-m", "book_cut.cli",
            "-i", str(input_img),
            "-o", str(tmp_path / "out"),
            "--dry-run",
            "--sample-n", "0",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert result.returncode != 0
    assert "sample-n" in result.stderr.lower() or "sample-n" in result.stdout.lower()


def test_cli_sample_n_without_dry_run_warns(tmp_path: Path, two_page_image: Image.Image, capsys):
    """``--sample-n N``（无 --dry-run）→ warn 后忽略。"""
    input_img = tmp_path / "test.png"
    two_page_image.save(input_img)

    result = subprocess.run(
        [
            sys.executable, "-m", "book_cut.cli",
            "-i", str(input_img),
            "-o", str(tmp_path / "out"),
            "--sample-n", "5",  # 无 --dry-run
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=_ENV,
    )
    # 正常处理（虽然输入是单图），退出码 0
    assert result.returncode == 0
    assert "--sample-n" in result.stdout


# ----------------------------------------------------------------------------
# 性能
# ----------------------------------------------------------------------------


@pytest.mark.slow
def test_dry_run_performance(synthetic_pdf_with_outline: Path, tmp_path: Path):
    """dry-run 3 页 + deskew + sauvola ≤ 10s。"""
    import time

    from book_cut.pipeline.orchestrator import run_pipeline

    preview = tmp_path / "preview"
    args = argparse.Namespace(
        input=str(synthetic_pdf_with_outline),
        output=str(tmp_path / "out"),
        split="gutter",
        crop="border",
        binarize="sauvola",
        deskew=True,
        format="png",
        pdf=False,
        page_order="ltr",
        outline=True,
        no_morph=False,
        pdf_page_size="keep",
        paper_pages=3,
        paper_deviation=30,
        dry_run=True,
        sample_n=3,
        preview_output=str(preview),
    )

    t0 = time.perf_counter()
    run_pipeline(args)
    elapsed = time.perf_counter() - t0
    assert elapsed < 10.0, f"dry-run 3 页耗时 {elapsed:.1f}s 超过阈值"
