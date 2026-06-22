"""v1.6+ C2 paper/trim 重复公式合并测试。

C2 改动：把 ``detect/paper.py`` 的 ``adaptive_padding`` 和灰度转换样板移到
``detect/_utils.py``，``detect/trim.py`` 的 ``_default_adaptive_padding`` 重复公式
被 ``detect._utils.adaptive_padding`` 取代。

验证点：
1. ``detect._utils.adaptive_padding`` 行为与 ``detect.paper.adaptive_padding`` 完全一致
2. ``detect.paper.adaptive_padding`` 仍可访问（向后兼容）
3. ``trim._default_adaptive_padding`` 已删除（去重）
4. 行为不破坏：trim_margins 输出与重构前一致
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PIL import Image

from book_cut.detect import paper as paper_mod
from book_cut.detect import trim as trim_mod
from book_cut.detect._utils import adaptive_padding, to_gray_array, to_L_image


# ============ _utils.adaptive_padding 与 paper.adaptive_padding 一致 ============


def test_c2_adaptive_padding_from_utils_same_as_paper():
    """C2：``_utils.adaptive_padding`` 与 ``paper.adaptive_padding`` 行为一致。"""
    assert paper_mod.adaptive_padding is adaptive_padding
    # 同一个函数对象（不是副本）
    assert inspect.getsource(paper_mod.adaptive_padding) == inspect.getsource(adaptive_padding)


@pytest.mark.parametrize(
    "h,w,expected",
    [
        (700, 700, 14),  # int(700*0.02) = 14
        (1500, 1500, 30),  # 30, capped
        (4000, 4000, 30),  # 80, clamped to 30
        (100, 100, 5),  # 2, floored
        (250, 250, 5),  # 5, exactly floor
        (1500, 500, 10),  # min(h,w)=500 → 10
    ],
)
def test_c2_adaptive_padding_scaling(h, w, expected):
    """C2：各尺寸 padding 公式正确。"""
    assert adaptive_padding(h, w) == expected
    assert paper_mod.adaptive_padding(h, w) == expected  # re-export 工作


# ============ trim._default_adaptive_padding 已删除 ============


def test_c2_trim_default_adaptive_padding_removed():
    """C2：``trim._default_adaptive_padding`` 被移除（公式合并到 _utils）。"""
    assert not hasattr(trim_mod, "_default_adaptive_padding"), (
        "trim._default_adaptive_padding 应该被移除并改用 _utils.adaptive_padding"
    )


# ============ paper.adaptive_padding 向后兼容 ============


def test_c2_paper_adaptive_padding_still_importable():
    """C2：``from book_cut.detect.paper import adaptive_padding`` 仍可导入（向后兼容）。"""
    from book_cut.detect.paper import adaptive_padding as ap_paper

    assert ap_paper is adaptive_padding


# ============ trim_margins 行为不变 ============


def test_c2_trim_margins_legacy_still_works():
    """C2：trim_margins legacy 模式（config=None）行为不变。"""
    img_arr = np.full((500, 500), 255, dtype=np.uint8)
    img_arr[100:400, 100:400] = 30
    img = Image.fromarray(img_arr, mode="L")

    # legacy 模式：threshold=240 default, padding=10 default
    out = trim_mod.trim_margins(img)
    # 内容 300×300（100:400）+ padding 10 → 320×320 (110:410)
    assert out.size == (320, 320)


def test_c2_trim_margins_adaptive_still_works():
    """C2：trim_margins adaptive 模式（config=CropConfig）行为不变。"""
    img_arr = np.full((500, 500), 255, dtype=np.uint8)
    img_arr[100:400, 100:400] = 30
    img = Image.fromarray(img_arr, mode="L")

    # adaptive 模式：config.padding=20 → 320+20=340? Actually 10*2=20 padding each side
    # content 100:400 → after -pad, +pad → max(0, 100-20):min(499, 400+20) = 80:420 → 340×340
    out = trim_mod.trim_margins(img, config=paper_mod.CropConfig(paper_color=255, padding=20))
    assert out.size == (340, 340)


def test_c2_trim_margins_adaptive_padding_none_uses_utils():
    """C2：``config.padding=None`` 时调 ``_utils.adaptive_padding``（不是 trim 的本地副本）。

    验证：500×500 输入 → adaptive_padding = max(5, int(500*0.02)) = 10。
    内容 100:400，padding 10 → 110:410 = 300×300。
    """
    img_arr = np.full((500, 500), 255, dtype=np.uint8)
    img_arr[100:400, 100:400] = 30
    img = Image.fromarray(img_arr, mode="L")

    # config.padding=None → 自适应
    out = trim_mod.trim_margins(img, config=paper_mod.CropConfig(paper_color=255, padding=None))
    # adaptive_padding(500, 500) = max(5, int(500*0.02)) = 10
    assert out.size == (320, 320)


# ============ to_gray_array / to_L_image 共享 ============


def test_c2_to_gray_array_rgb_input():
    """C2：``_utils.to_gray_array`` 自动转灰度。"""
    img = Image.new("RGB", (50, 50), (220, 200, 180))
    arr = to_gray_array(img)
    assert arr.shape == (50, 50)
    assert arr.dtype == np.uint8


def test_c2_to_gray_array_already_L():
    """C2：``_utils.to_gray_array`` 对 L 图直接 asarray。"""
    img = Image.new("L", (50, 50), 200)
    arr = to_gray_array(img)
    assert arr.shape == (50, 50)
    assert arr.dtype == np.uint8


def test_c2_to_L_image_roundtrip():
    """C2：``_utils.to_L_image`` 从 ndarray 返回 L mode PIL。"""
    arr = np.full((100, 100), 200, dtype=np.uint8)
    img = to_L_image(arr)
    assert img.mode == "L"
    assert img.size == (100, 100)


# ============ paper.estimate_paper_color 仍工作 ============


def test_c2_estimate_paper_color_still_works():
    """C2：``paper.estimate_paper_color`` 重构后行为不变。"""
    img = Image.new("L", (100, 100), 220)
    pc = paper_mod.estimate_paper_color(img)
    assert pc == 220.0


def test_c2_estimate_paper_color_uses_utils_to_gray():
    """C2：``paper.estimate_paper_color`` 内部走 ``_utils.to_gray_array``。"""
    # 通过 mock/spy 间接验证：to_gray_array 被调用
    from unittest.mock import patch

    img = Image.new("L", (50, 50), 200)
    real_arr = np.full((50, 50), 200, dtype=np.uint8)
    with patch("book_cut.detect.paper.to_gray_array", return_value=real_arr) as spy:
        paper_mod.estimate_paper_color(img)
        spy.assert_called_once_with(img)


# ============ to_gray_array 接受 dtype 参数 ============


def test_c2_to_gray_array_supports_float32():
    """C2：``_utils.to_gray_array`` 支持 float32 dtype（Sauvola 需要）。"""
    img = Image.new("L", (50, 50), 200)
    arr = to_gray_array(img, dtype=np.float32)
    assert arr.dtype == np.float32
    assert arr.shape == (50, 50)