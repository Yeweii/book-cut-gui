"""测试公用夹具：合成一张已知中缝/版框的双页图 + 带 outline 的合成 PDF。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


@pytest.fixture()
def two_page_image() -> Image.Image:
    """合成一张 800x500 的双页图：左右各有内容，中间是白色中缝。"""
    w, h = 800, 500
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    # 左侧内容（一些黑色块）
    for y in range(50, 450, 40):
        draw.rectangle([(50, y), (350, y + 20)], fill="black")

    # 右侧内容
    for y in range(50, 450, 40):
        draw.rectangle([(450, y), (750, y + 20)], fill="black")

    # 中缝在 x = 380~420（白色）
    # 不画任何东西，保持白色
    return img


@pytest.fixture()
def two_page_image_with_border() -> Image.Image:
    """合成带版框的双页图：左右各有一个矩形版框，中间是版框间隙。"""
    w, h = 800, 500
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    # 左版框：(80, 60) - (380, 440)
    draw.rectangle([(80, 60), (380, 440)], outline="black", width=2)
    # 右侧内容
    for y in range(100, 400, 40):
        draw.rectangle([(100, y), (360, y + 15)], fill="black")

    # 右版框：(420, 60) - (720, 440)
    draw.rectangle([(420, 60), (720, 440)], outline="black", width=2)
    for y in range(100, 400, 40):
        draw.rectangle([(440, y), (700, y + 15)], fill="black")

    return img


@pytest.fixture()
def tmp_output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


# ----------------------------------------------------------------------------
# v1.4：合成带 outline 的 PDF
# ----------------------------------------------------------------------------


def _make_double_page_png() -> bytes:
    """合成一张 800x500 双页 PNG（左/右各 5 条黑块，中间 380-420 白），返回 bytes。"""
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    for y in range(50, 450, 40):
        draw.rectangle([(50, y), (350, y + 20)], fill="black")
        draw.rectangle([(450, y), (750, y + 20)], fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def synthetic_pdf_with_outline(tmp_path: Path) -> Path:
    """构造 5 页 PDF + 1 级 outline + metadata。

    - 第 1 页 = "封面"（page 1）
    - 第 2-4 页 = "卷一/卷二/卷三"（page 2/3/4）
    - 第 5 页 = "封底"（page 5）
    - metadata: title="古籍测试" / author="甲"
    """
    import pymupdf

    doc = pymupdf.open()
    doc.set_metadata(
        {
            "title": "古籍测试",
            "author": "甲",
            "subject": "v1.4 outline 测试",
            "keywords": "book-cut, test",
            "creator": "conftest",
        }
    )
    png_bytes = _make_double_page_png()
    for _ in range(5):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    doc.set_toc(
        [
            [1, "封面", 1],
            [1, "卷一", 2],
            [1, "卷二", 3],
            [1, "卷三", 4],
            [1, "封底", 5],
        ]
    )
    out = tmp_path / "synthetic.pdf"
    doc.save(str(out))
    doc.close()
    return out


@pytest.fixture()
def synthetic_pdf_no_outline(tmp_path: Path) -> Path:
    """构造 3 页 PDF，无 outline + 有 metadata。"""
    import pymupdf

    doc = pymupdf.open()
    doc.set_metadata({"title": "无书签测试", "author": "乙"})
    png_bytes = _make_double_page_png()
    for _ in range(3):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    out = tmp_path / "no_outline.pdf"
    doc.save(str(out))
    doc.close()
    return out


@pytest.fixture()
def synthetic_pdf_nested_outline(tmp_path: Path) -> Path:
    """构造 5 页 PDF + 3 级嵌套 outline（卷/章/节）。"""
    import pymupdf

    doc = pymupdf.open()
    png_bytes = _make_double_page_png()
    for _ in range(5):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    # 卷一(page 1) → 章1(page 1) → 节1.1(page 1) + 节1.2(page 2)
    # 卷二(page 3) → 章3(page 3)
    doc.set_toc(
        [
            [1, "卷一", 1],
            [2, "第一章", 1],
            [3, "1.1 节", 1],
            [3, "1.2 节", 2],
            [1, "卷二", 3],
            [2, "第三章", 3],
        ]
    )
    out = tmp_path / "nested.pdf"
    doc.save(str(out))
    doc.close()
    return out

