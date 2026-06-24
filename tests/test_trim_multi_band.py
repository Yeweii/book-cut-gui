"""v2.1 trim G 方案：多 band 豁免（双页扫描右侧副页保留）。

场景：双页扫描 + ``--split none``，用户想保留右侧副页 / 版心装饰。
方案 D 单 band 只覆盖中央版心；扩展为多 band 支持任意列区间。

TDD：先写 RED（参数不存在 → TypeError），再 GREEN。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from book_cut.detect.trim import _filter_main_components, trim_margins

# ----------------------------------------------------------------------------
# 合成 fixture：双 band 验证（左边缘 + 右边缘）
# ----------------------------------------------------------------------------


def _page_with_left_and_right_strips() -> Image.Image:
    """1200×800 白纸：
    - 左侧贯穿版框线（x=10-15, y=0-800）→ CCA 应滤
    - 右侧贯穿版框线（x=1185-1190, y=0-800）→ CCA 应滤
    - 左侧副页装饰条（x∈[100, 200], y∈[710, 764]）→ 在 band (0.1, 0.2) 内，CCA 应保留
    - 右侧副页装饰条（x∈[1000, 1100], y∈[710, 764]）→ 在 band (0.83, 0.92) 内，CCA 应保留

    不画顶/底版框线 —— 避免 col 0 也有 ink 的检查失败。
    """
    img = Image.new("RGB", (1200, 800), "white")
    draw = ImageDraw.Draw(img)
    # 左版框线
    draw.rectangle([(10, 0), (15, 800)], fill="black")
    # 右版框线
    draw.rectangle([(1185, 0), (1190, 800)], fill="black")
    # 左侧副页装饰条
    for y in range(710, 714):
        for x in range(100, 200):
            draw.point((x, y), fill="black")
    for y in range(760, 764):
        for x in range(100, 200):
            draw.point((x, y), fill="black")
    for y in range(714, 760):
        for x in range(148, 152):
            draw.point((x, y), fill="black")
    # 右侧副页装饰条
    for y in range(710, 714):
        for x in range(1000, 1100):
            draw.point((x, y), fill="black")
    for y in range(760, 764):
        for x in range(1000, 1100):
            draw.point((x, y), fill="black")
    for y in range(714, 760):
        for x in range(1048, 1052):
            draw.point((x, y), fill="black")
    return img


def _double_band_synthetic() -> Image.Image:
    """2000×800 双 band 测试：左侧装饰 (col 200-300) + 右侧装饰 (col 1700-1800)。

    gutter_bands = [(0.1, 0.15), (0.85, 0.9)] → 两端装饰都保留。
    不带 band 时：左右装饰都会因 aspect > 10 被滤 → 退化。
    """
    img = Image.new("RGB", (2000, 800), "white")
    draw = ImageDraw.Draw(img)
    # 左侧装饰条 (col 200-300)
    for y in range(380, 384):
        for x in range(200, 300):
            draw.point((x, y), fill="black")
    for y in range(420, 424):
        for x in range(200, 300):
            draw.point((x, y), fill="black")
    # 右侧装饰条 (col 1700-1800)
    for y in range(380, 384):
        for x in range(1700, 1800):
            draw.point((x, y), fill="black")
    for y in range(420, 424):
        for x in range(1700, 1800):
            draw.point((x, y), fill="black")
    return img


# ----------------------------------------------------------------------------
# 私有 API：_filter_main_components 接受 gutter_bands list
# ----------------------------------------------------------------------------


def test_filter_main_components_accepts_gutter_bands_list() -> None:
    """``_filter_main_components`` 支持 ``gutter_bands: list[tuple]``。

    RED: 当前只支持 ``gutter_band: tuple`` → 传 list 会走不到 in_gutter 分支。
    """
    mask = np.zeros((100, 200), dtype=bool)
    # 中央一个高 aspect 连通区（被默认滤掉）
    mask[40:60, 90:110] = True  # 20×20 → aspect 1.0，不滤
    # 左侧 band 内：高 aspect 连通区（应保留）
    mask[10:90, 30:34] = True  # 4×80 → aspect 20.0
    out = _filter_main_components(
        mask,
        min_area=10,
        gutter_bands=[(0.1, 0.2)],  # band 覆盖 col 20-40，左侧装饰 cx=32 在内
    )
    # 左侧装饰条（aspect 20）应在 band 内被保留
    assert out[10:90, 30:34].any(), "gutter_bands 内高 aspect 连通区应保留"
    # 中央连通区（aspect 1.0）正常保留
    assert out[40:60, 90:110].all(), "中央正常连通区应保留"


def test_filter_main_components_multi_band_preserves_both_sides() -> None:
    """``gutter_bands`` 多 band：左右两侧装饰都保留。

    RED: 当前单 band 只覆盖一侧。
    """
    mask = np.zeros((800, 2000), dtype=bool)
    # 左侧装饰条 (col 200-300) → cx=250 → band (0.1, 0.15) = col 200-300
    mask[380:384, 200:300] = True
    mask[420:424, 200:300] = True
    # 右侧装饰条 (col 1700-1800) → cx=1750 → band (0.85, 0.9) = col 1700-1800
    mask[380:384, 1700:1800] = True
    mask[420:424, 1700:1800] = True
    out = _filter_main_components(
        mask,
        min_area=10,
        gutter_bands=[(0.1, 0.15), (0.85, 0.9)],
    )
    # 左侧装饰应保留
    assert out[380:424, 200:300].any(), "左侧 band 内装饰应保留"
    # 右侧装饰应保留
    assert out[380:424, 1700:1800].any(), "右侧 band 内装饰应保留"


def test_filter_main_components_single_band_still_works() -> None:
    """向后兼容：旧 ``gutter_band: tuple`` 仍可用（应仍走 in_gutter 分支）。

    RED: 当前 single band 正常工作 → 此 test 应 PASS（不在 RED 内）。
    """
    mask = np.zeros((100, 200), dtype=bool)
    mask[10:90, 30:34] = True  # band (0.1, 0.2) = col 20-40
    out = _filter_main_components(
        mask,
        min_area=10,
        gutter_band=(0.1, 0.2),
    )
    assert out[10:90, 30:34].any(), "旧 gutter_band tuple 应仍生效"


# ----------------------------------------------------------------------------
# 公共 API：trim_margins / _trim_margins_from_array 接受 gutter_bands
# ----------------------------------------------------------------------------


def test_trim_margins_accepts_gutter_bands_list() -> None:
    """``trim_margins`` 公共 API 支持 ``gutter_bands: list[tuple]``。

    RED: 当前签名不接受 gutter_bands → TypeError。
    """
    img = _page_with_left_and_right_strips()
    out = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_bands=[(0.08, 0.17), (0.83, 0.92)],  # 左 + 右 band
    )
    # 输出应包含左侧装饰（col 100-200）和右侧装饰（col 1000-1100）
    arr = np.asarray(out.convert("L"))
    # 输出图像中应有 ink（左侧或右侧装饰任一保留即通过）
    assert (arr < 200).any(), "gutter_bands 列表未生效 → 装饰全被滤光"


def test_trim_margins_gutter_bands_preserves_both_sides() -> None:
    """双 band：左右两侧装饰都保留 → 输出 W 涵盖左+右装饰列。"""
    img = _double_band_synthetic()
    out_single = trim_margins(
        img, padding=5, min_component_ratio=0.0001, gutter_band=(0.85, 0.9)
    )
    out_multi = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_bands=[(0.1, 0.15), (0.85, 0.9)],
    )
    # 多 band 输出 W 应大于单 band 输出 W（左+右都保留）
    assert out_multi.size[0] > out_single.size[0], (
        f"gutter_bands 双 band 输出 W {out_multi.size[0]} 应 > "
        f"gutter_band 单 band 输出 W {out_single.size[0]}"
    )


def test_trim_margins_backward_compat_single_band() -> None:
    """向后兼容：``gutter_band: tuple`` 仍可用（旧代码路径）。"""
    img = _page_with_left_and_right_strips()
    out_old = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_band=(0.08, 0.17),  # 单 band 覆盖左侧装饰
    )
    out_new_list = trim_margins(
        img,
        padding=5,
        min_component_ratio=0.0001,
        gutter_bands=[(0.08, 0.17)],  # 列表单 band 等价
    )
    # 两种写法输出一致
    assert out_old.size == out_new_list.size, (
        f"gutter_band tuple 与 gutter_bands 单元素列表输出不一致: "
        f"{out_old.size} vs {out_new_list.size}"
    )


# ----------------------------------------------------------------------------
# 真实样本：尸子图右侧副页保留
# ----------------------------------------------------------------------------


@pytest.fixture()
def shizi_sample_path() -> str:
    sample = Path(__file__).resolve().parent.parent / "samples" / "尸子卷上下.浙江书局.光绪三年刊_0021.png"
    if not sample.exists():
        pytest.skip(f"尸子样本不存在: {sample}")
    return str(sample)


def test_trim_gutter_bands_preserves_shizi_right_side(shizi_sample_path: str) -> None:
    """尸子图 + 多 band（中央 + 右侧）→ 输出 W 应比单 band 大（右侧副页保留）。

    尸子图 6400×8534：
    - 主页面在左侧 (col 0-2800)
    - 右侧副页内容在 col 3500-4500 (版心区 col 3500-6400)
    - 单 band (0.35, 0.5) = col 2240-3200 → 只覆盖中央，右侧被裁
    - 多 band [(0.35, 0.5), (0.55, 0.75)] → 右侧副页保留

    验证：多 band 输出 W > 单 band 输出 W。
    """
    img = Image.open(shizi_sample_path)
    out_single = trim_margins(
        img,
        padding=0,
        extra_padding=30,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_band=(0.35, 0.5),
    )
    out_multi = trim_margins(
        img,
        padding=0,
        extra_padding=30,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_bands=[(0.35, 0.5), (0.55, 0.75)],
    )
    # 多 band 输出 W 应 > 单 band 输出 W（右侧副页被保留）
    assert out_multi.size[0] > out_single.size[0], (
        f"gutter_bands 多 band 输出 W {out_multi.size[0]} 应 > "
        f"gutter_band 单 band 输出 W {out_single.size[0]} → 右侧副页未保留"
    )


# ----------------------------------------------------------------------------
# CLI flag：--trim-gutter-bands
# ----------------------------------------------------------------------------


def test_cli_trim_gutter_bands_flag_accepted() -> None:
    """``--trim-gutter-bands`` flag 存在（v2.1+ G 方案）。"""
    import os
    import subprocess
    import sys

    _ROOT = Path(__file__).resolve().parent.parent
    _SRC = _ROOT / "src"
    _ENV = {**os.environ, "PYTHONPATH": str(_SRC)}

    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-gutter-bands" in result.stdout, (
        "--trim-gutter-bands flag 应存在，但 help 文本中未找到"
    )
