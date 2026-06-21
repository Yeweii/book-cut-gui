"""测试公用夹具：合成一张已知中缝/版框的双页图。"""

from __future__ import annotations

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
