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
    img = _gray_with_text()
    out = binarize_otsu(img)
    assert out.mode == "L"
    arr = np.asarray(out)
    # 输出只有 0 和 255
    unique = set(np.unique(arr).tolist())
    assert unique.issubset({0, 255})


def test_adaptive_returns_L_mode():
    img = _gray_with_text()
    out = binarize_adaptive(img, block_size=21, C=5)
    assert out.mode == "L"


def test_sauvola_returns_L_mode():
    img = _gray_with_text()
    out = binarize_sauvola(img, window_size=15)
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
