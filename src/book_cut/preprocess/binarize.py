"""二值化：Otsu / Adaptive / Sauvola（默认）。"""

from __future__ import annotations

import os
import platform

import cv2
import numpy as np
from PIL import Image

# v1.5+ A2：Sauvola 局部均方的后端选择
# OpenCV 在 arm64 NEON 上对 boxFilter 优化更好（multiply + filter 两次 SIMD pass），
# sqrBoxFilter 在 x86_64 AVX 上更快（fused squaring 一次 pass）。
# 实测（macOS arm64，2026-06-21）：4000×4000 Sauvola
#   boxFilter(arr*arr)  : 61.7-61.8ms ✓
#   sqrBoxFilter(arr)   : 78.8-110.0ms ✗
# 平台默认 + 环境变量 ``BOOKCUT_BINARIZE`` 覆盖（值：``sqrbox`` / ``box``）。
_X86_ARCHES = frozenset({"x86_64", "AMD64", "i386", "i686", "x86"})
_DEFAULT_USE_SQRBOX = platform.machine() in _X86_ARCHES
_USE_SQRBOX = (
    os.environ.get("BOOKCUT_BINARIZE", "sqrbox" if _DEFAULT_USE_SQRBOX else "box").lower()
    == "sqrbox"
)


def _local_mean_sq(arr: np.ndarray, ksize: tuple[int, int]) -> np.ndarray:
    """局部均方（v1.5+ A2 后端选择）。

    x86_64 → ``cv2.sqrBoxFilter``（fused，无临时数组）
    arm64/其他 → ``cv2.boxFilter(arr * arr)``（multiply 后 filter，NEON 优化更佳）

    可用 ``BOOKCUT_BINARIZE=sqrbox|box`` 覆盖默认。
    """
    if _USE_SQRBOX:
        return cv2.sqrBoxFilter(arr, -1, ksize)
    return cv2.boxFilter(arr * arr, -1, ksize)


def _to_gray_array(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.float32)


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    return Image.fromarray(arr_u8, mode="L")


def binarize_otsu(image: Image.Image) -> Image.Image:
    """Otsu 全局阈值二值化。"""
    arr = _to_gray_array(image).astype(np.uint8)
    _threshold, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _to_L_image(binary)


def binarize_adaptive(
    image: Image.Image,
    block_size: int = 31,
    C: int = 10,
) -> Image.Image:
    """OpenCV 自适应阈值（高斯加权），适合光照不均的扫描件。"""
    arr = _to_gray_array(image).astype(np.uint8)
    binary = cv2.adaptiveThreshold(
        arr,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        C,
    )
    return _to_L_image(binary)


def binarize_sauvola(
    image: Image.Image,
    window_size: int = 25,
    k: float = 0.2,
    R: float = 128.0,
) -> Image.Image:
    """Sauvola 局部自适应二值化（**推荐用于古籍**）。

    对纸张泛黄、不均匀光照等情况效果好。

    后端选择：v1.5+ A2 —— 平台自动 + ``BOOKCUT_BINARIZE`` 环境变量覆盖。

    Args:
        image: 输入图像（任意模式）。
        window_size: 局部窗口大小（奇数），默认 25。
        k: 阈值公式系数，默认 0.2（古籍常用 0.2~0.5）。
        R: 灰度动态范围（0~255），默认 128。
    """
    arr = _to_gray_array(image)

    # 强制奇数窗口
    if window_size % 2 == 0:
        window_size += 1
    ksize = (window_size, window_size)

    # 局部均值
    mean = cv2.boxFilter(arr, -1, ksize)
    # 局部均方（v1.5+ A2：平台后端选择，详见 _local_mean_sq）
    mean_sq = _local_mean_sq(arr, ksize)
    # 局部标准差（数值稳定化）
    var = np.maximum(mean_sq - mean * mean, 0.0)
    std = np.sqrt(var)

    # Sauvola 阈值
    threshold = mean * (1.0 + k * (std / R - 1.0))

    # 文字通常比背景深，文字像素 < 阈值；因此 THRESH_BINARY_INV
    binary = np.where(arr < threshold, 0, 255).astype(np.uint8)
    return _to_L_image(binary)


def binarize(
    image: Image.Image,
    method: str = "sauvola",
    **kwargs,
) -> Image.Image:
    """二值化分派。

    Args:
        image: 输入图像。
        method: 'otsu' | 'adaptive' | 'sauvola' | 'none'。
        kwargs: 传递给具体算法的参数。
    """
    method = method.lower()
    if method in ("none", "", "off"):
        return image
    if method == "otsu":
        return binarize_otsu(image)
    if method == "adaptive":
        return binarize_adaptive(image, **kwargs)
    if method == "sauvola":
        return binarize_sauvola(image, **kwargs)
    raise ValueError(f"未知二值化方法: {method}")
