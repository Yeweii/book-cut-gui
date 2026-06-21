"""v1.4 outline 保留测试。

覆盖：
- 单元：inject_outline_and_metadata 的页号映射、嵌套、关停
- 集成：run_pipeline 端到端对带 outline 的合成 PDF 走一遍
"""

from __future__ import annotations

import argparse
from pathlib import Path

from book_cut.io.exporter import (
    STANDARD_METADATA_KEYS,
    inject_outline_and_metadata,
    save_pdf,
)
from book_cut.io.loader import get_pdf_metadata, get_pdf_outline
from book_cut.pipeline import run_pipeline

# ----------------------------------------------------------------------------
# 辅助：构造 / 解析 outline
# ----------------------------------------------------------------------------


def _make_blank_pdf(path: Path, n: int = 5) -> None:
    """构造 n 页空白 PDF。"""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(n):
        doc.new_page(width=400, height=400)
    doc.save(str(path))
    doc.close()


def _flatten_outline(reader, items=None, depth: int = 0) -> list[tuple[int, str, int]]:
    """把 pypdf 的嵌套 outline 展平成 [(level, title, page_0idx), ...]。"""
    if items is None:
        items = reader.outline
    out: list[tuple[int, str, int]] = []
    for item in items:
        if isinstance(item, list):
            out.extend(_flatten_outline(reader, item, depth + 1))
        else:
            page_num = reader.get_destination_page_number(item)
            out.append((depth, item.title, page_num))
    return out


# ----------------------------------------------------------------------------
# T1-T5, T11：单元测试 inject_outline_and_metadata
# ----------------------------------------------------------------------------


def test_t1_flat_outline_ltr(tmp_path: Path) -> None:
    """T1：5 页 + 一级 outline + LTR 1:2 切分 → 输出 outline 节点 5 个，title 一致，页号映射正确。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=5)
    image_paths = [tmp_path / f"img_{i:04d}.png" for i in range(10)]
    # 构造 10 张白图（用 PIL 现拉）
    from PIL import Image

    for p in image_paths:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(image_paths, src)  # 这步只是占位——我们重写 src

    toc = [(1, "封面", 1), (1, "卷一", 2), (1, "卷二", 3), (1, "卷三", 4), (1, "封底", 5)]
    mapping = {0: [0, 1], 1: [2, 3], 2: [4, 5], 3: [6, 7], 4: [8, 9]}
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [
        (0, "封面", 0),
        (0, "卷一", 2),
        (0, "卷二", 4),
        (0, "卷三", 6),
        (0, "封底", 8),
    ]


def test_t3_ltr_1to2_points_to_first(tmp_path: Path) -> None:
    """T3：LTR 1:2 → outline 指向第一张（左）。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=2)
    from PIL import Image

    images = [tmp_path / f"img_{i:04d}.png" for i in range(4)]
    for p in images:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(images, src)

    toc = [(1, "卷一", 1), (1, "卷二", 2)]
    mapping = {0: [0, 1], 1: [2, 3]}  # LTR
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [(0, "卷一", 0), (0, "卷二", 2)]  # 指向 [0, 2]，不是 [1, 3]


def test_t4_rtl_1to2_points_to_first(tmp_path: Path) -> None:
    """T4：RTL 1:2 → mapping 已是 [右, 左]，outline 指向第一张（右）。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=2)
    from PIL import Image

    images = [tmp_path / f"img_{i:04d}.png" for i in range(4)]
    for p in images:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(images, src)

    toc = [(1, "卷一", 1), (1, "卷二", 2)]
    # pipeline 已经把 sub_pages 翻成 [右, 左]，所以 mapping 是 reversed
    mapping = {0: [1, 0], 1: [3, 2]}
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [(0, "卷一", 1), (0, "卷二", 3)]


def test_t5_nested_outline_preserved(tmp_path: Path) -> None:
    """T5：3 级嵌套 outline（卷/章/节）层级保留。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=5)
    from PIL import Image

    images = [tmp_path / f"img_{i:04d}.png" for i in range(10)]
    for p in images:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(images, src)

    toc = [
        (1, "卷一", 1),
        (2, "第一章", 1),
        (3, "1.1 节", 1),
        (3, "1.2 节", 2),
        (1, "卷二", 3),
        (2, "第三章", 3),
    ]
    mapping = {i: [2 * i, 2 * i + 1] for i in range(5)}
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [
        (0, "卷一", 0),
        (1, "第一章", 0),
        (2, "1.1 节", 0),
        (2, "1.2 节", 2),
        (0, "卷二", 4),
        (1, "第三章", 4),
    ]


def test_t2_1to1_mapping(tmp_path: Path) -> None:
    """T2：1:1 切分时（单页检测命中），mapping 单元素，outline 指向该页。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=3)
    from PIL import Image

    images = [tmp_path / f"img_{i:04d}.png" for i in range(3)]
    for p in images:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(images, src)

    toc = [(1, "封面", 1), (1, "卷一", 2), (1, "封底", 3)]
    mapping = {0: [0], 1: [1], 2: [2]}  # 1:1
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [(0, "封面", 0), (0, "卷一", 1), (0, "封底", 2)]


def test_t11_mixed_1to1_and_1to2(tmp_path: Path) -> None:
    """T11：1:1 + 1:2 混合 → outline 按各自 mapping 指向。"""
    src = tmp_path / "blank.pdf"
    _make_blank_pdf(src, n=3)
    from PIL import Image

    images = [tmp_path / f"img_{i:04d}.png" for i in range(5)]
    for p in images:
        Image.new("RGB", (100, 100), "white").save(p)
    save_pdf(images, src)

    # 1:1 封面 + 1:2 卷一 + 1:1 封底 → 5 输出页
    toc = [(1, "封面", 1), (1, "卷一", 2), (1, "封底", 3)]
    mapping = {0: [0], 1: [1, 2], 2: [3]}  # 中间多一页空隙（页 4 是空）
    out_pdf = tmp_path / "out.pdf"
    inject_outline_and_metadata(src, out_pdf, toc, {}, mapping)

    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    assert flat == [(0, "封面", 0), (0, "卷一", 1), (0, "封底", 3)]


# ----------------------------------------------------------------------------
# T6-T9, T8：集成测试（端到端 pipeline）
# ----------------------------------------------------------------------------


def _run_pipeline_with_pdf(
    pdf_in: Path,
    out_dir: Path,
    *,
    page_order: str = "ltr",
    outline: bool = True,
    no_single_page: bool = True,
) -> None:
    args = argparse.Namespace(
        input=str(pdf_in),
        output=str(out_dir),
        split="half",  # 1:1 对半切，确定性最高
        deskew=False,
        crop="none",
        crop_adaptive="auto",
        paper_pages=5,
        binarize="none",
        format="png",
        pdf=True,
        page_order=page_order,
        outline=outline,
        auto_single_page=not no_single_page,
        half_offset=0,
    )
    run_pipeline(args)


def test_t6_no_outline_flag(tmp_path: Path, synthetic_pdf_with_outline: Path) -> None:
    """T6：--no-outline → 输出 PDF 无 outline 但图片正常。"""
    out_dir = tmp_path / "out"
    _run_pipeline_with_pdf(synthetic_pdf_with_outline, out_dir, outline=False)

    out_pdf = out_dir / "synthetic.pdf"
    assert out_pdf.exists()
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    # 关闭 outline 时 _write_pdf_with_outline 直接 save_pdf，跳过 inject
    assert _flatten_outline(r) == []


def test_t7_source_pdf_no_outline(tmp_path: Path, synthetic_pdf_no_outline: Path) -> None:
    """T7：原 PDF 无 outline → 输出 PDF 也无 outline，无报错。"""
    out_dir = tmp_path / "out"
    _run_pipeline_with_pdf(synthetic_pdf_no_outline, out_dir)

    out_pdf = out_dir / "no_outline.pdf"
    assert out_pdf.exists()
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    assert _flatten_outline(r) == []


def test_t8_metadata_passthrough(tmp_path: Path, synthetic_pdf_with_outline: Path) -> None:
    """T8：metadata 透传，producer 追加 book-cut。"""
    out_dir = tmp_path / "out"
    _run_pipeline_with_pdf(synthetic_pdf_with_outline, out_dir)

    out_pdf = out_dir / "synthetic.pdf"
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    info = dict(r.metadata or {})
    assert info.get("/Title") == "古籍测试"
    assert info.get("/Author") == "甲"
    assert info.get("/Subject") == "v1.4 outline 测试"
    assert info.get("/Keywords") == "book-cut, test"
    assert "book-cut" in info.get("/Producer", "")


def test_t9_pdf_input_without_pdf_flag(
    tmp_path: Path, synthetic_pdf_with_outline: Path
) -> None:
    """T9：PDF 输入但 --pdf 不开 → 不输出 PDF，pipeline 正常。"""
    args = argparse.Namespace(
        input=str(synthetic_pdf_with_outline),
        output=str(tmp_path / "out"),
        split="half",
        deskew=False,
        crop="none",
        crop_adaptive="auto",
        paper_pages=5,
        binarize="none",
        format="png",
        pdf=False,  # 关键：不生成 PDF
        page_order="ltr",
        outline=True,
        auto_single_page=False,
        half_offset=0,
    )
    run_pipeline(args)

    out_dir = tmp_path / "out"
    assert not (out_dir / "synthetic.pdf").exists()
    # 图片应已生成
    assert any(out_dir.glob("*.png"))


def test_end_to_end_outline_and_metadata(
    tmp_path: Path, synthetic_pdf_with_outline: Path
) -> None:
    """端到端：合成 PDF → 切分 → 合并 PDF → outline + metadata 完整。"""
    out_dir = tmp_path / "out"
    _run_pipeline_with_pdf(synthetic_pdf_with_outline, out_dir)

    out_pdf = out_dir / "synthetic.pdf"
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    # 5 页 × split half → 10 输出页（offset 0 = 对半切，每页 → 2 张）
    # 1-based → 0-based：封面=1→0, 卷一=2→2, 卷二=3→4, 卷三=4→6, 封底=5→8
    assert flat == [
        (0, "封面", 0),
        (0, "卷一", 2),
        (0, "卷二", 4),
        (0, "卷三", 6),
        (0, "封底", 8),
    ]


def test_end_to_end_rtl_1to2(
    tmp_path: Path, synthetic_pdf_with_outline: Path
) -> None:
    """端到端 + RTL：split gutter + page-order rtl → outline 指向第一张（output index 0, 2, ...）。

    "只指第一张" 拍板：不管 LTR 还是 RTL，输出页号都是 0, 2, 4, ...。
    LTR 时第一张是左页，RTL 时第一张是右页——但页号一样。
    """
    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(synthetic_pdf_with_outline),
        output=str(out_dir),
        split="gutter",  # 用真正的 1:2 切分
        deskew=False,
        crop="none",
        crop_adaptive="auto",
        paper_pages=5,
        binarize="none",
        format="png",
        pdf=True,
        page_order="rtl",
        outline=True,
        auto_single_page=False,
        half_offset=0,
    )
    run_pipeline(args)

    out_pdf = out_dir / "synthetic.pdf"
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    # RTL 1:2：原 page i → output [右(2i), 左(2i+1)]，outline 指右 = 2i
    assert flat == [
        (0, "封面", 0),
        (0, "卷一", 2),
        (0, "卷二", 4),
        (0, "卷三", 6),
        (0, "封底", 8),
    ]


def test_nested_outline_end_to_end(
    tmp_path: Path, synthetic_pdf_nested_outline: Path
) -> None:
    """端到端：3 级嵌套 outline 完整保留。"""
    out_dir = tmp_path / "out"
    _run_pipeline_with_pdf(synthetic_pdf_nested_outline, out_dir)

    out_pdf = out_dir / "nested.pdf"
    import pypdf

    r = pypdf.PdfReader(str(out_pdf))
    flat = _flatten_outline(r)
    # 5 页 × split half → 10 输出页；每原页 → [2i, 2i+1] (LTR)
    assert flat == [
        (0, "卷一", 0),
        (1, "第一章", 0),
        (2, "1.1 节", 0),
        (2, "1.2 节", 2),
        (0, "卷二", 4),
        (1, "第三章", 4),
    ]


# ----------------------------------------------------------------------------
# 辅助函数：loader 的 outline/metadata 抓取
# ----------------------------------------------------------------------------


def test_get_pdf_outline_shape(synthetic_pdf_with_outline: Path) -> None:
    """get_pdf_outline 返回 list[tuple[int, str, int]]。"""
    toc = get_pdf_outline(synthetic_pdf_with_outline)
    assert toc == [
        (1, "封面", 1),
        (1, "卷一", 2),
        (1, "卷二", 3),
        (1, "卷三", 4),
        (1, "封底", 5),
    ]


def test_get_pdf_metadata_keys(synthetic_pdf_with_outline: Path) -> None:
    """get_pdf_metadata 返回标准 /Info 键。"""
    meta = get_pdf_metadata(synthetic_pdf_with_outline)
    assert meta.keys() <= STANDARD_METADATA_KEYS
    assert meta["/Title"] == "古籍测试"
    assert meta["/Author"] == "甲"


def test_get_pdf_outline_empty(synthetic_pdf_no_outline: Path) -> None:
    """无 outline 的 PDF → 空列表。"""
    assert get_pdf_outline(synthetic_pdf_no_outline) == []
