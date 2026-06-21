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
