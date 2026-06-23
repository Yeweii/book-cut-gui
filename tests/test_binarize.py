"""二值化测试。"""

from __future__ import annotations

import importlib

import numpy as np
from PIL import Image

from book_cut.preprocess import binarize as binarize_mod
from book_cut.preprocess.binarize import (
    binarize,
    binarize_adaptive,
    binarize_otsu,
    binarize_sauvola,
)


def _gray_with_text() -> Image.Image:
    """合成一张有文字的灰度图：白底+黑块。"""
    arr = np.full((100, 200), 255, dtype=np.uint8)
    arr[20:40, 20:180] = 30  # 一行黑条
    arr[60:80, 20:180] = 30
    return Image.fromarray(arr, mode="L")


def test_otsu_returns_L_mode():
    """v2.0+：opt-in ``binary_mode='8bit'`` 保留 v1.9 L 模式行为。"""
    img = _gray_with_text()
    out = binarize_otsu(img, binary_mode="8bit")
    assert out.mode == "L"
    arr = np.asarray(out)
    # 输出只有 0 和 255
    unique = set(np.unique(arr).tolist())
    assert unique.issubset({0, 255})


def test_adaptive_returns_L_mode():
    """v2.0+：opt-in ``binary_mode='8bit'`` 保留 v1.9 L 模式行为。"""
    img = _gray_with_text()
    out = binarize_adaptive(img, block_size=21, C=5, binary_mode="8bit")
    assert out.mode == "L"


def test_sauvola_returns_L_mode():
    """v2.0+：opt-in ``binary_mode='8bit'`` 保留 v1.9 L 模式行为。"""
    img = _gray_with_text()
    out = binarize_sauvola(img, window_size=15, binary_mode="8bit")
    assert out.mode == "L"


def test_sauvola_detects_text():
    """Sauvola 应能识别黑条。"""
    img = _gray_with_text()
    out = binarize_sauvola(img, window_size=15)
    arr = np.asarray(out)
    # 文字区像素应大部分为 0（黑）
    text_region = arr[20:40, 20:180]
    black_ratio = (text_region == 0).sum() / text_region.size
    assert black_ratio > 0.5


def test_dispatch_none():
    img = _gray_with_text()
    out = binarize(img, "none")
    assert out is img  # 原图直通


def test_dispatch_invalid_raises():
    img = _gray_with_text()
    import pytest

    with pytest.raises(ValueError):
        binarize(img, "unknown")


def test_binarize_preserves_dimensions():
    img = _gray_with_text()
    out = binarize_sauvola(img)
    assert out.size == img.size


# ----------------------------------------------------------------------------
# v1.5+ A2：后端选择（平台自动 + BOOKCUT_BINARIZE 环境变量覆盖）
# ----------------------------------------------------------------------------


def _reload_binarize_with_env(env_value: str | None) -> None:
    """用指定环境变量 reload binarize 模块，触发 _USE_SQRBOX 重新求值。"""
    import os

    if env_value is None:
        os.environ.pop("BOOKCUT_BINARIZE", None)
    else:
        os.environ["BOOKCUT_BINARIZE"] = env_value
    importlib.reload(binarize_mod)


def test_backend_default_matches_platform():
    """默认后端应与平台匹配：x86 → sqrbox，其他（含 arm64）→ box。"""
    import platform

    expected = "sqrbox" if platform.machine() in binarize_mod._X86_ARCHES else "box"
    _reload_binarize_with_env(None)
    assert binarize_mod._USE_SQRBOX is (expected == "sqrbox")


def test_backend_env_box_override():
    """BOOKCUT_BINARIZE=box 强制用 boxFilter。"""
    _reload_binarize_with_env("box")
    try:
        assert binarize_mod._USE_SQRBOX is False
        img = _gray_with_text()
        out = binarize_sauvola(img, window_size=15)
        arr = np.asarray(out)
        assert arr.shape == (100, 200)
        # 输出仍能识别文字（boxFilter 路径）
        text_region = arr[20:40, 20:180]
        black_ratio = (text_region == 0).sum() / text_region.size
        assert black_ratio > 0.5
    finally:
        _reload_binarize_with_env(None)


def test_backend_env_sqrbox_override():
    """BOOKCUT_BINARIZE=sqrbox 强制用 sqrBoxFilter。"""
    _reload_binarize_with_env("sqrbox")
    try:
        assert binarize_mod._USE_SQRBOX is True
        img = _gray_with_text()
        out = binarize_sauvola(img, window_size=15)
        arr = np.asarray(out)
        assert arr.shape == (100, 200)
        # 输出仍能识别文字（sqrBoxFilter 路径）
        text_region = arr[20:40, 20:180]
        black_ratio = (text_region == 0).sum() / text_region.size
        assert black_ratio > 0.5
    finally:
        _reload_binarize_with_env(None)


# ----------------------------------------------------------------------------
# v2.0 binary_mode：默认 1-bit 紧凑输出
# ----------------------------------------------------------------------------


def test_otsu_default_returns_1bit():
    """v2.0 默认 binary_mode='1bit'，otsu 应返回 mode='1'。"""
    img = _gray_with_text()
    out = binarize_otsu(img)
    assert out.mode == "1"


def test_adaptive_default_returns_1bit():
    """v2.0 默认 binary_mode='1bit'，adaptive 应返回 mode='1'。"""
    img = _gray_with_text()
    out = binarize_adaptive(img, block_size=21, C=5)
    assert out.mode == "1"


def test_sauvola_default_returns_1bit():
    """v2.0 默认 binary_mode='1bit'，sauvola 应返回 mode='1'。"""
    img = _gray_with_text()
    out = binarize_sauvola(img, window_size=15)
    assert out.mode == "1"


def test_dispatch_default_returns_1bit():
    """v2.0 默认 binary_mode='1bit'，binarize 调度应透传给子函数。"""
    img = _gray_with_text()
    out = binarize(img, "sauvola", window_size=15)
    assert out.mode == "1"


def test_explicit_8bit_legacy_compat():
    """binary_mode='8bit' 保留 v1.9 行为，mode='L'。"""
    img = _gray_with_text()
    for fn_name, kwargs in [
        ("binarize_otsu", {}),
        ("binarize_adaptive", {"block_size": 21, "C": 5}),
        ("binarize_sauvola", {"window_size": 15}),
    ]:
        fn = globals()[fn_name]
        out = fn(img, binary_mode="8bit", **kwargs)
        assert out.mode == "L", f"{fn_name} 8bit 模式应返回 L，实际 {out.mode}"


def test_1bit_value_equivalence_to_8bit():
    """1-bit 与 8-bit 像素值等价：8bit // 255 == 1bit 像素。"""
    img = _gray_with_text()
    out_8 = binarize_sauvola(img, window_size=15, binary_mode="8bit")
    out_1 = binarize_sauvola(img, window_size=15, binary_mode="1bit")
    arr_8 = np.asarray(out_8)
    arr_1 = np.asarray(out_1).astype(np.uint8)  # bool → 0/1
    np.testing.assert_array_equal(arr_8 // 255, arr_1)


def test_1bit_png_size_shrink():
    """synthetic 4000×5000 二值页，1-bit PNG 应比 8-bit PNG 小至少 30%。

    注：实际缩比取决于熵（clean text 可达 4-8x，noisy 1.5-2x）。本测试只验证
    1-bit *总是更小*，不卡死具体倍数。真实尸子图跑全流程可达 5-8x。
    """
    import os
    import tempfile

    rng = np.random.default_rng(42)
    # 95% 白 + 5% 黑：binarize 后 1-bit 1/0 比 ≈ 19:1
    arr = np.full((5000, 4000), 240, dtype=np.uint8)  # 偏黄纸
    mask = rng.random((5000, 4000)) < 0.05
    arr[mask] = 30  # 文字
    img = Image.fromarray(arr, mode="L")
    with tempfile.TemporaryDirectory() as tmp:
        p_8 = os.path.join(tmp, "p8.png")
        p_1 = os.path.join(tmp, "p1.png")
        binarize_sauvola(img, window_size=25, k=0.2, binary_mode="8bit").save(p_8, optimize=True)
        binarize_sauvola(img, window_size=25, k=0.2, binary_mode="1bit").save(p_1, optimize=True)
        size_8 = os.path.getsize(p_8)
        size_1 = os.path.getsize(p_1)
    # 1-bit 应至少比 8-bit 小 30%
    assert size_1 < size_8 * 0.7, (
        f"1-bit ({size_1/1024:.0f} KB) 应比 8-bit ({size_8/1024:.0f} KB) 至少小 30%，"
        f"实际缩减 {(1 - size_1/size_8)*100:.1f}%"
    )


def test_dispatch_none_ignores_binary_mode():
    """binarize_method='none' 不走二值化，binary_mode 不影响（保持原图 mode）。"""
    img = _gray_with_text()  # mode="L"
    out = binarize(img, "none", binary_mode="1bit")
    assert out is img
    assert out.mode == "L"


def test_dispatch_invalid_method_8bit_raises():
    """binary_mode='8bit' 时无效方法仍抛 ValueError。"""
    import pytest

    img = _gray_with_text()
    with pytest.raises(ValueError):
        binarize(img, "unknown", binary_mode="8bit")
