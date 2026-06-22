"""v1.7 PDF 页面统一尺寸测试。

覆盖（14 个）：
- 解析（8）：4 个预设 / max/first 不需解析 / custom 合法 / custom 错格式
- fit（4）：横→竖 / 竖→横 / 正方形 / 同尺寸
- 实际 PDF（2）：a4 / max mediabox 验证
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from book_cut.io.page_size import (
    PDF_PAGE_SIZE_CHOICES,
    PRESETS,
    fit_to_canvas,
    parse_page_size_px,
)
from book_cut.pipeline import run_pipeline

# ----------------------------------------------------------------------------
# T1-T8：parse_page_size_px
# ----------------------------------------------------------------------------


def test_t1_parse_a4() -> None:
    """T1：a4 → 210×297 mm @ 96 DPI = (794, 1123) px。"""
    assert parse_page_size_px("a4") == (794, 1123)


def test_t2_parse_a5() -> None:
    """T2：a5 → 148×210 mm @ 96 DPI = (559, 794) px。"""
    assert parse_page_size_px("a5") == (559, 794)


def test_t3_parse_letter() -> None:
    """T3：letter → 8.5×11 in @ 96 DPI = (816, 1056) px。"""
    assert parse_page_size_px("letter") == (816, 1056)


def test_t4_parse_legal() -> None:
    """T4：legal → 8.5×14 in @ 96 DPI = (816, 1344) px。"""
    assert parse_page_size_px("legal") == (816, 1344)


def test_t5_parse_custom_mm() -> None:
    """T5：custom 280×200 mm → (1058, 756) px（96 DPI）。"""
    w, h = parse_page_size_px("custom", "280x200", "mm")
    assert (w, h) == (1058, 756)


def test_t6_parse_custom_inch_px_match() -> None:
    """T6：custom 11×8.5 inch = 1056×816 px（验证单位换算与 letter 关系正确）。"""
    w, h = parse_page_size_px("custom", "11x8.5", "inch")
    assert (w, h) == (1056, 816)


def test_t7_parse_custom_bad_dim() -> None:
    """T7：custom 缺 dim 或格式错 → ValueError。"""
    with pytest.raises(ValueError, match="custom 需要配合"):
        parse_page_size_px("custom")
    with pytest.raises(ValueError, match="格式错"):
        parse_page_size_px("custom", "280,200", "mm")  # 用逗号错


def test_t8_parse_unknown_token() -> None:
    """T8：未知 token → ValueError（带合法 choices 提示）。"""
    with pytest.raises(ValueError, match="未知"):
        parse_page_size_px("bogus")  # type: ignore[arg-type]


# ----------------------------------------------------------------------------
# T9-T12：fit_to_canvas
# ----------------------------------------------------------------------------


def test_t9_fit_landscape_to_portrait() -> None:
    """T9：横图 (800x500) fit 竖目标 (794x1123) → 输出 (794, 1123)，短边贴 (500/1123=0.445 < 800/794=1.008 → scale=0.445)。"""
    img = Image.new("L", (800, 500), 200)
    out = fit_to_canvas(img, 794, 1123)
    assert out.size == (794, 1123)
    assert out.mode == "L"


def test_t10_fit_portrait_to_landscape() -> None:
    """T10：竖图 (500x800) fit 横目标 (816x1056) → 输出 (816, 1056)，scale 约 0.66。"""
    img = Image.new("L", (500, 800), 200)
    out = fit_to_canvas(img, 816, 1056)
    assert out.size == (816, 1056)
    assert out.mode == "L"


def test_t11_fit_to_square() -> None:
    """T11：正方形 target (600x600) + 任意 input → 输出 (600, 600)。"""
    img = Image.new("RGB", (500, 500), (100, 50, 25))
    out = fit_to_canvas(img, 600, 600)
    assert out.size == (600, 600)
    assert out.mode == "RGB"


def test_t12_fit_same_size() -> None:
    """T12：子图与 target 同尺寸 (100x100) → scale=1，输出仍 (100, 100)。"""
    img = Image.new("L", (100, 100), 200)
    out = fit_to_canvas(img, 100, 100)
    assert out.size == (100, 100)


# ----------------------------------------------------------------------------
# T13-T14：实际 PDF mediabox 验证（端到端）
# ----------------------------------------------------------------------------


def _make_pdf_with_image(path: Path, w_pt: int, h_pt: int) -> None:
    """构造一页 PDF（指定 points），嵌入一张白图。"""
    doc = pymupdf.open()
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()


def _make_pdf_multi_size(path: Path, sizes: list[tuple[int, int]]) -> None:
    """构造多页 PDF，每页 points 尺寸不同。"""
    doc = pymupdf.open()
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
    for w_pt, h_pt in sizes:
        page = doc.new_page(width=w_pt, height=h_pt)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()


def test_t13_a4_actual_pdf_mediabox(tmp_path: Path) -> None:
    """T13：--pdf-page-size a4 → 输出 PDF 每页 mediabox = (595, 842) pt（A4 标准）。

    img2pdf 默认按 96 DPI 把像素换算到 points（1 inch = 96 px = 72 pt），
    所以 794×1123 px 图像 → (794/96*72, 1123/96*72) = (595.5, 842.25) pt。
    """
    in_pdf = tmp_path / "in.pdf"
    _make_pdf_with_image(in_pdf, 800, 600)  # 任意 input size

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf),
        output=str(out_dir),
        split="half",  # 强制 1:2
        crop="none",
        binarize="none",
        deskew=False,
        auto_single_page=False,
        page_order="ltr",
        outline=False,
        format="png",
        crop_adaptive="auto",
        paper_pages=1,
        paper_deviation=30,
        half_offset=0,
        no_morph=False,
        pdf=True,
        # v1.7：
        pdf_page_size="a4",
        pdf_page_dim=None,
        pdf_page_unit="mm",
    )
    run_pipeline(args)

    out_pdf = out_dir / "in.pdf"
    assert out_pdf.exists()

    r = pymupdf.open(str(out_pdf))
    try:
        for page in r:
            mb = page.mediabox
            w_pt = mb.width
            h_pt = mb.height
            # A4: 210×297 mm = 595×842 pt（允许 ±1 浮点误差）
            assert abs(w_pt - 595.5) < 1, f"width {w_pt} not A4"
            assert abs(h_pt - 842.25) < 1, f"height {h_pt} not A4"
    finally:
        r.close()


def test_t14_max_actual_pdf_mediabox(tmp_path: Path) -> None:
    """T14：--pdf-page-size max → 输出 PDF 每页 mediabox = max(W)×max(H) of input pages (in points)。

    输入 2 页 (500, 700) 和 (800, 400) → max = (800, 700) px
    → img2pdf 96 DPI 换算 → (600, 525) pt。
    """
    in_pdf = tmp_path / "in.pdf"
    _make_pdf_multi_size(in_pdf, [(500, 700), (800, 400)])

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf),
        output=str(out_dir),
        split="half",
        crop="none",
        binarize="none",
        deskew=False,
        auto_single_page=False,
        page_order="ltr",
        outline=False,
        format="png",
        crop_adaptive="auto",
        paper_pages=1,
        paper_deviation=30,
        half_offset=0,
        no_morph=False,
        pdf=True,
        # v1.7：
        pdf_page_size="max",
        pdf_page_dim=None,
        pdf_page_unit="mm",
    )
    run_pipeline(args)

    out_pdf = out_dir / "in.pdf"
    assert out_pdf.exists()

    r = pymupdf.open(str(out_pdf))
    try:
        seen = set()
        for page in r:
            mb = page.mediabox
            seen.add((round(mb.width, 1), round(mb.height, 1)))
        # max(W)=800, max(H)=700 in px → (600, 525) pt @ 96 DPI
        assert seen == {(600.0, 525.0)}, f"got {seen}"
    finally:
        r.close()


# ----------------------------------------------------------------------------
# 辅助：test_pdf_page_size_choice_in_cli
# ----------------------------------------------------------------------------


def test_t15_pdf_page_size_choice_in_cli() -> None:
    """T15：--pdf-page-size 在 choices 列表里。"""
    for c in ("keep", "max", "first", "a4", "a5", "letter", "legal", "custom"):
        assert c in PDF_PAGE_SIZE_CHOICES
    assert len(PRESETS) == 4  # a4, a5, letter, legal
