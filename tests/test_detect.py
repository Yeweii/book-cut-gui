"""detect 模块测试：trim + border。"""

from __future__ import annotations

from PIL import Image, ImageDraw

from book_cut.detect.border import crop_to_border
from book_cut.detect.trim import trim_margins


def _page_with_white_margins() -> Image.Image:
    """合成一张 600x400 的单页：白边 + 黑边框 + 文字。"""
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    # 版框 (80,60) - (520,340)
    draw.rectangle([(80, 60), (520, 340)], outline="black", width=3)
    # 文字行
    for y in range(80, 320, 30):
        draw.line([(100, y), (500, y)], fill="black", width=2)
    return img


def _page_with_heavy_white_margins() -> Image.Image:
    """四周有明显白边的图。"""
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    # 内容集中在中间 200x150
    for y in range(80, 220, 25):
        draw.line([(100, y), (300, y)], fill="black", width=2)
    return img


def test_trim_cuts_white_margins():
    img = _page_with_heavy_white_margins()
    out = trim_margins(img, padding=2)
    # 输出应比原图小
    assert out.size[0] < img.size[0]
    assert out.size[1] < img.size[1]


def test_trim_keeps_content_box():
    """trim 应切到内容外边界 + padding。"""
    img = _page_with_white_margins()
    out = trim_margins(img, padding=5)
    # 版框在 (80,60)-(520,340)，外加 padding 5
    # 输出应大致是这个范围
    w, h = out.size
    assert w == 520 - 80 + 1 + 2 * 5
    assert h == 340 - 60 + 1 + 2 * 5


def test_border_crops_inside_frame():
    img = _page_with_white_margins()
    out = crop_to_border(img, padding=2)
    # 版框在 (80,60)-(520,340)，内含 padding 约 2
    # 输出应大致是这个范围
    w, h = out.size
    assert w <= 520 - 80 + 4
    assert h <= 340 - 60 + 4
    assert w > 100  # 不能裁没了


def test_border_fallback_to_trim():
    """没有明显版框时回退到 trim。"""
    img = _page_with_heavy_white_margins()
    # 这里没有连续版框线，应回退到 trim
    out = crop_to_border(img)
    assert out.size != img.size  # 应有裁切
