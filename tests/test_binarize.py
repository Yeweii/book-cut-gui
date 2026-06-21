"""二值化测试。"""

from __future__ import annotations

import numpy as np
from PIL import Image

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
