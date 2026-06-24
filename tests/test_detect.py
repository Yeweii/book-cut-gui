"""detect 模块测试：trim + border + paper。"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from book_cut.detect.border import crop_to_border
from book_cut.detect.paper import (
    CropConfig,
    adaptive_padding,
    aggregate_paper_color,
    default_crop_config,
    estimate_paper_color,
)
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


# ============ paper color & adaptive crop 测试 (v1.3) ============


def test_paper_color_estimator_white_image():
    """纯白图 → 255.0 (clipped 95th percentile)."""
    img = Image.new("RGB", (300, 200), "white")
    assert estimate_paper_color(img) == 255.0


def test_paper_color_estimator_yellowed_paper():
    """灰度 200 的"泛黄"纸 → ~195 (clip 下限 180)."""
    arr = np.full((200, 300), 200, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    val = estimate_paper_color(img)
    assert 180.0 <= val <= 200.0


def test_paper_color_estimator_robust_to_dense_ink():
    """半白半黑（模拟 ZHSY cover）→ 255.0 (95th percentile 仍是白)."""
    arr = np.full((200, 300), 255, dtype=np.uint8)
    arr[:, 150:] = 0  # 右半全黑
    img = Image.fromarray(arr, mode="L")
    assert estimate_paper_color(img) == 255.0


def test_aggregate_paper_color_median_robust_to_outlier():
    """一页异常值不应拉低书级 paper color."""
    colors = [240.0, 245.0, 248.0, 250.0, 100.0]  # 100 是 cover 异常
    assert aggregate_paper_color(colors) == 245.0  # median


def test_aggregate_paper_color_empty():
    """空列表兜底 255.0."""
    assert aggregate_paper_color([]) == 255.0


def test_aggregate_paper_color_single():
    """单元素直接返回."""
    assert aggregate_paper_color([233.5]) == 233.5


def test_adaptive_padding_scaling():
    """按尺寸缩放: 700→14, 1500→30 (cap), 4000→30 (cap), 100→5 (floor)."""
    assert adaptive_padding(700, 700) == 14  # int(700*0.02)=14
    assert adaptive_padding(1500, 1500) == 30  # int(1500*0.02)=30, cap
    assert adaptive_padding(4000, 4000) == 30  # int(4000*0.02)=80, clamp to 30
    assert adaptive_padding(100, 100) == 5  # int(100*0.02)=2, floor


def test_default_crop_config_ink_threshold():
    """ink_threshold = max(paper_color - ink_offset, 60)."""
    c = CropConfig(paper_color=240.0, ink_offset=30.0)
    assert c.ink_threshold == 210.0
    # 极低 paper 不应塌缩
    c2 = CropConfig(paper_color=50.0, ink_offset=30.0)
    assert c2.ink_threshold == 60.0


def test_default_crop_config_factory():
    """default_crop_config: 显式 paper_color 时直接用；None 时用 240."""
    assert default_crop_config().paper_color == 240.0
    assert default_crop_config(245.0).paper_color == 245.0
    assert default_crop_config(None).paper_color == 240.0


# ----- trim_margins 自适应模式测试 -----


def test_trim_adaptive_matches_fixed_on_white_paper():
    """白底/黑墨 fixture：adaptive 与 fixed 输出尺寸完全相同 (回归钉子)."""
    img = _page_with_white_margins()
    fixed = trim_margins(img, padding=5)
    adaptive = trim_margins(
        img,
        config=CropConfig(paper_color=255.0, padding=5, min_edge_ink=3),
    )
    assert adaptive.size == fixed.size


def test_trim_adaptive_handles_yellowed_paper():
    """灰墨 80 + 黄纸 200：fixed (thr=240) 把纸误当内容，adaptive (thr=170) 正确."""
    arr = np.full((300, 400), 200, dtype=np.uint8)  # 黄纸
    # 内部画一个 80 灰的"内容框"
    arr[80:220, 100:300] = 80
    img = Image.fromarray(arr, mode="L")

    fixed = trim_margins(img, padding=2)  # thr=240, 200<240 → 把整个纸当内容
    adaptive = trim_margins(
        img,
        config=CropConfig(paper_color=200.0, padding=2, min_edge_ink=3),
    )  # thr=170, 200>170 → 纸正确判为纸
    # adaptive 应裁得更小（紧贴内容框），fixed 会保留更多黄色"内容"
    assert adaptive.size[0] < fixed.size[0] or adaptive.size[1] < fixed.size[1]


def test_border_fallback_uses_adaptive_config():
    """border 检测失败回退到 trim 时也要用 adaptive config."""
    # 用 _page_with_heavy_white_margins：内容在中间，无明显版框矩形，
    # border 检测必失败，触发 trim fallback
    img = _page_with_heavy_white_margins()
    cfg = CropConfig(paper_color=240.0, padding=2, min_edge_ink=3)
    adaptive = crop_to_border(img, config=cfg)
    expected = trim_margins(img, config=cfg)
    assert adaptive.size == expected.size
