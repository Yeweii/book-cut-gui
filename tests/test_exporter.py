"""exporter 模块测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from book_cut.io.exporter import save_image, save_pdf


def test_save_png(tmp_output_dir: Path):
    img = Image.new("RGB", (50, 50), "red")
    p = save_image(img, tmp_output_dir, "book", 1, fmt="png")
    assert p.exists()
    assert p.suffix == ".png"
    assert p.name == "book_0001.png"


def test_save_jpg_quality(tmp_output_dir: Path):
    img = Image.new("RGB", (50, 50), "red")
    p = save_image(img, tmp_output_dir, "book", 2, fmt="jpg", quality=80)
    assert p.exists()
    assert p.suffix == ".jpg"


def test_save_pdf(tmp_output_dir: Path):
    paths = []
    for i in range(3):
        img = Image.new("RGB", (200, 300), (i * 80, 100, 200))
        paths.append(save_image(img, tmp_output_dir, "p", i, fmt="png"))
    pdf = save_pdf(paths, tmp_output_dir / "out.pdf")
    assert pdf.exists()
    assert pdf.stat().st_size > 1000
