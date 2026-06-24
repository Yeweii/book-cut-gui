"""v2.1 trim D 方案测试：版心保护区（鱼尾保留）。

对应提案：``docs/dev/2026-06-24-v2.1-trim-yuwei-preserve.md``（待写）

核心思路：CCA 滤波只对边缘（版框线常见位置）生效；版心（gutter band）的连通区
豁免，避免把鱼尾装饰条误当作版框线滤掉。

TDD 约定：先写 RED（参数不存在 → TypeError），再实现 GREEN。
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from book_cut.detect.trim import _trim_margins_from_array, trim_margins

# ----------------------------------------------------------------------------
# 合成 fixture
# ----------------------------------------------------------------------------


def _page_with_yuwei_at_center_and_border_at_edge() -> Image.Image:
    """1200×800 白纸：
    - 左侧贯穿版框线（x=10-15, y=0-800）→ CCA 应滤
    - 中央版心鱼尾装饰：x∈[560,640], y∈[710,764]（80px 居中）→ CCA 应保留

    不画顶/底版框线 —— 它们会污染输出 col=0 检查（顶/底横线跨整宽 → col 0 也有 ink）。
    """
    img = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(img)
    # 左版框线（贯穿）—— 用矩形画线，aspect 100+ 触发 aspect 过滤
    draw.rectangle([(10, 0), (15, 800)], fill="black")
    # 中央版心鱼尾（三角装饰）—— 全部在 col 560-640（版心 0.4-0.6 = col 480-720 内）
    # 上边线
    for y in range(710, 714):
        for x in range(560, 640):
            draw.point((x, y), fill="black")
    # 下边线
    for y in range(760, 764):
        for x in range(560, 640):
            draw.point((x, y), fill="black")
    # 中线（鱼尾的"指针"）
    for y in range(714, 760):
        for x in range(598, 602):
            draw.point((x, y), fill="black")
    return img


def _page_with_only_yuwei() -> Image.Image:
    """800×800 白纸，只有中央版心鱼尾装饰（无版框）。"""
    img = Image.new("RGB", (800, 800), "white")
    draw = ImageDraw.Draw(img)
    # 中央鱼尾 (col 360-440, row 360-440)
    for y in range(370, 374):
        for x in range(360, 440):
            draw.point((x, y), fill="black")
    for y in range(420, 424):
        for x in range(360, 440):
            draw.point((x, y), fill="black")
    for y in range(374, 420):
        for x in range(398, 402):
            draw.point((x, y), fill="black")
    return img


# ----------------------------------------------------------------------------
# 方案 D：版心保护区
# ----------------------------------------------------------------------------


def test_trim_yuwei_param_default_no_protection() -> None:
    """不传版心参数时行为与旧版一致（向后兼容，保留 A/B/C 默认）。"""
    img = _page_with_only_yuwei()
    # 默认无版心保护 + min_component_ratio > 0 → 鱼尾装饰（多横线 + 中线，area 较大但 aspect 也大）会被滤
    # 但单像素鱼尾装饰条在 aspect > 10 下被滤掉，鱼尾 bbox 退化
    out_default = trim_margins(img, padding=5)
    out_explicit = trim_margins(img, padding=5, gutter_band=(0.4, 0.6))
    # 显式版心保护应能保留鱼尾 → 输出更大
    assert out_explicit.size[1] >= out_default.size[1] - 5  # 容许 1-2 px bbox 抖动


def test_trim_yuwei_preserve_at_center() -> None:
    """鱼尾在版心 → 启用版心保护后鱼尾不被裁。

    RED: 当前参数不存在 → TypeError。
    """
    img = _page_with_yuwei_at_center_and_border_at_edge()
    out_protected = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_band=(0.4, 0.6),  # 中央 20% 宽版心
    )
    # 输出应包含版心区域：bbox bottom ≥ 760（鱼尾底部）
    # 输出宽应该足够包含 col 560-640（鱼尾横坐标范围）
    arr = np.asarray(out_protected.convert("L"))
    # 输出图像中应有鱼尾的 ink（中央 bottom 区有 ink）
    bottom_strip = arr[-200:, :]  # 最底 200 行
    assert (bottom_strip < 200).any(), "鱼尾区域应有 ink"


def test_trim_yuwei_only_filter_no_protection() -> None:
    """只有鱼尾无版框的图，启用版心保护：鱼尾应完整保留。

    验证：output image 应包含 ink（鱼尾未被滤光 → bbox 不退化）。
    RED: 当前参数不存在 → TypeError。
    """
    img = _page_with_only_yuwei()
    out_protected = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_band=(0.4, 0.6),
    )
    arr = np.asarray(out_protected.convert("L"))
    # 输出应有 ink（鱼尾 bbox 在 padding 之内）
    rows_with_ink = np.where((arr < 200).any(axis=1))[0]
    assert len(rows_with_ink) > 0, "输出无 ink — 鱼尾被滤光"
    # 输出尺寸应覆盖鱼尾 bbox (370-423) + padding (5 each side) ≈ 365-428 → H ≈ 63
    # 鱼尾中心在版心 (col 360-440) → 输出 col 范围约 355-445 → W ≈ 90
    assert out_protected.size[1] >= 50, f"输出 H {out_protected.size[1]} 过小 → 鱼尾被裁"
    assert out_protected.size[0] >= 60, f"输出 W {out_protected.size[0]} 过小 → 鱼尾被裁"


def test_trim_yuwei_from_array_accepted() -> None:
    """``_trim_margins_from_array`` 私有 API 也支持 gutter_band。"""
    img = _page_with_yuwei_at_center_and_border_at_edge()
    arr = np.asarray(img.convert("L"))
    out = _trim_margins_from_array(
        arr,
        padding=5,
        min_component_ratio=0.0001,
        gutter_band=(0.4, 0.6),
    )
    assert out.size[0] > 0 and out.size[1] > 0


def test_trim_yuwei_filter_at_edge_still_works() -> None:
    """版心保护启用后，边缘版框线仍被滤（不应破坏方案 B 收益）。

    对比：同一张图，gutter_band 启用 vs 不启用，输出尺寸应相近（都裁掉了
    左侧贯穿版框线 col 10-15，但保留版心鱼尾 col 560-640）。
    鱼尾 area 320/184（顶/中线），用 ratio=0.0001 让其通过 area 检查。
    """
    img = _page_with_yuwei_at_center_and_border_at_edge()
    out_default = trim_margins(img, padding=5, min_component_ratio=0.0001)
    out_protected = trim_margins(
        img, padding=5, min_component_ratio=0.0001, gutter_band=(0.4, 0.6)
    )
    # 默认输出 + 保护输出：size 应相近（鱼尾 bbox + padding ≈ 90×64）
    # 默认无版心保护时，版框线被 aspect 滤 + 鱼尾被 gutter 豁免 → size 应相同
    assert out_protected.size == out_default.size, (
        f"输出不一致: default={out_default.size} protected={out_protected.size}"
    )
    # 输出应紧贴版心鱼尾（不是全图 1200×800）
    assert out_protected.size[0] < 200, (
        f"输出 W {out_protected.size[0]} 过大 → 版框线漏过滤"
    )


# ----------------------------------------------------------------------------
# 真实样本 fixture（尸子图）
# ----------------------------------------------------------------------------


@pytest.fixture()
def shizi_sample_path() -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sample = root / "samples" / "尸子卷上下.浙江书局.光绪三年刊_0021.png"
    if not sample.exists():
        pytest.skip(f"尸子样本不存在: {sample}")
    return str(sample)


def test_trim_yuwei_preserves_shizi_bottom_yuwei(
    shizi_sample_path: str,
) -> None:
    """v2.1+ D：尸子图 + gutter_band + A+B → 底部鱼尾应在输出内。

    尸子图为双页扫描 (6400x8534)。底部鱼尾位于 col ~2234-2883 (在版心
    (0.35-0.5) 内 = col 2240-3200)，row 7986-8060。

    验证：开启版心保护 + 适当 extra_padding → 输出 H 应涵盖鱼尾底部。
    mask 起点 row ~1784（CCA 后），鱼尾底部 8060 → 输出 H 应 ≥ (8060-1784) + 60 ≈ 6336
    """
    img = Image.open(shizi_sample_path)
    out = trim_margins(
        img,
        padding=0,
        extra_padding=30,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_band=(0.35, 0.5),  # 鱼尾中心 col ~2558 → 0.35-0.5 = 2240-3200 覆盖
    )
    out_w, out_h = out.size  # PIL: (W, H)
    assert out_h >= 6300, f"output H {out_h} < 6300 → 鱼尾被裁"
