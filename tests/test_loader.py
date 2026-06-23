"""loader 模块测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from book_cut.io.loader import iter_pages


def _make_jpeg(path: Path, color: tuple[int, int, int] = (200, 200, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), color).save(path, "JPEG")
    return path


def test_iter_image_file(tmp_path: Path):
    p = _make_jpeg(tmp_path / "a.jpg")
    pages = list(iter_pages(p))
    assert len(pages) == 1
    assert pages[0].source_name == "a"
    assert pages[0].image.size == (100, 100)


def test_iter_folder_nested(tmp_path: Path):
    _make_jpeg(tmp_path / "b.jpg")
    _make_jpeg(tmp_path / "sub" / "c.png")
    _make_jpeg(tmp_path / "ignored.txt")  # 非图片，应被忽略
    pages = list(iter_pages(tmp_path))
    # 2 个图片
    assert len(pages) == 2
    names = {p.source_name for p in pages}
    assert names == {"b", "c"}


def test_iter_pages_sorted(tmp_path: Path):
    _make_jpeg(tmp_path / "z.jpg")
    _make_jpeg(tmp_path / "a.jpg")
    _make_jpeg(tmp_path / "m.jpg")
    pages = list(iter_pages(tmp_path))
    names = [p.source_name for p in pages]
    assert names == ["a", "m", "z"]


def test_not_found(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        list(iter_pages(tmp_path / "no_such"))


def test_unsupported_ext(tmp_path: Path):
    p = tmp_path / "foo.xyz"
    p.write_text("hi")
    with pytest.raises(ValueError):
        list(iter_pages(p))


# ============ v1.9.2+ 渲染失败容错 ============


def test_iter_pdf_continues_on_render_failure(tmp_path: Path, monkeypatch):
    """v1.9.2+：单页 get_pixmap 失败时不让整本 PDF 中断 → 生成占位图继续。

    真实场景：MuPDF 遇到不识别的 image filter 抛
    "Error -3 while decompressing data: unknown compression method"，
    旧版会立刻 crash 整本 PDF。
    """
    import pymupdf

    from book_cut.io.loader import _iter_pdf

    # 合成 1 页真 PDF
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((50, 50), "hello", fontsize=20)
    pdf_path = tmp_path / "fake.pdf"
    doc.save(str(pdf_path))
    doc.close()

    # Monkeypatch get_pixmap：让所有渲染尝试都失败
    def fake_get_pixmap(self, *args, **kwargs):
        raise RuntimeError(
            "Error -3 while decompressing data: unknown compression method"
        )

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", fake_get_pixmap)

    pages = list(_iter_pdf(pdf_path))
    # 应产出 1 页（占位图）而不是抛异常中断
    assert len(pages) == 1
    # 占位图应是 1200x1600 白底
    img = pages[0].image
    assert img.size == (1200, 1600)
    assert img.mode == "RGB"
    # 抽样几个像素验证是白底
    assert img.getpixel((100, 100)) == (255, 255, 255)


def test_iter_pdf_no_failure(tmp_path: Path):
    """v1.9.2+：正常 PDF 不走占位路径。"""
    import pymupdf

    from book_cut.io.loader import _iter_pdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((50, 50), "hello", fontsize=20)
    pdf_path = tmp_path / "good.pdf"
    doc.save(str(pdf_path))
    doc.close()

    pages = list(_iter_pdf(pdf_path))
    assert len(pages) == 1
    # 正常渲染 400x600 @ 300 DPI = 1667x2500 左右
    img = pages[0].image
    assert img.size[0] > 1000  # 至少证明渲染了
    assert img.size[1] > 1000


def test_render_page_pixmap_fallback(monkeypatch):
    """v1.9.2+：_render_page_pixmap 第一个策略失败时尝试后续策略。"""
    from book_cut.io.loader import _render_page_pixmap

    # mock page
    class MockPage:
        def __init__(self):
            self.calls = 0

        def get_pixmap(self, matrix=None, alpha=False):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first attempt fails")
            # 第二次成功
            class MockPix:
                width = 100
                height = 100
                samples = b"\xff" * (100 * 100 * 3)

            return MockPix()

    page = MockPage()
    import pymupdf

    pix = _render_page_pixmap(page, pymupdf.Matrix(1, 1))
    assert pix is not None
    assert page.calls == 2  # 第一次失败，第二次成功


def test_render_page_pixmap_all_fail(monkeypatch):
    """v1.9.2+：所有策略都失败时抛出最后一个错误。"""
    from book_cut.io.loader import _render_page_pixmap

    class MockPage:
        def get_pixmap(self, matrix=None, alpha=False):
            raise RuntimeError("all fail")

    import pymupdf

    with pytest.raises(RuntimeError, match="all fail"):
        _render_page_pixmap(MockPage(), pymupdf.Matrix(1, 1))
