"""v2.3.3+ count_pages() 测试。

覆盖：
- 单 PDF / 单图片 / 文件夹混合 / 嵌套 / 不存在 / 不支持类型
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from book_cut.io.loader import count_pages


def _make_pdf(path: Path, n_pages: int) -> None:
    """构造 n_pages 页的空 PDF。"""
    doc = pymupdf.open()
    for _ in range(n_pages):
        doc.new_page(width=400, height=600)
    doc.save(str(path))
    doc.close()


def test_single_pdf(tmp_path: Path) -> None:
    """T1：5 页 PDF → count = 5。"""
    p = tmp_path / "a.pdf"
    _make_pdf(p, 5)
    assert count_pages(p) == 5


def test_single_image(tmp_path: Path) -> None:
    """T2：单张 PNG → count = 1。"""
    img = tmp_path / "a.png"
    Image.new("RGB", (100, 100), "white").save(img)
    assert count_pages(img) == 1


def test_folder_mixed(tmp_path: Path) -> None:
    """T3：2 个 PDF (3 + 2 页) + 4 张图 = 9。"""
    _make_pdf(tmp_path / "a.pdf", 3)
    _make_pdf(tmp_path / "b.pdf", 2)
    for i in range(4):
        Image.new("RGB", (50, 50), "white").save(tmp_path / f"img{i}.png")
    assert count_pages(tmp_path) == 9


def test_nested_folder(tmp_path: Path) -> None:
    """T4：递归子目录里的 PDF 也计入。"""
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    _make_pdf(sub / "x.pdf", 7)
    assert count_pages(tmp_path) == 7


def test_nonexistent(tmp_path: Path) -> None:
    """T5：路径不存在 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="不存在"):
        count_pages(tmp_path / "nope.pdf")


def test_unsupported(tmp_path: Path) -> None:
    """T6：未知扩展名 → ValueError。"""
    f = tmp_path / "weird.xyz"
    f.write_text("x")
    with pytest.raises(ValueError, match="不支持"):
        count_pages(f)


def test_empty_folder(tmp_path: Path) -> None:
    """T7：空目录 → count = 0（边界）。"""
    assert count_pages(tmp_path) == 0
