"""降噪（v1.9+）：清尘点 / 扫描噪点。

三档实现（由 ``BOOKCUT_PREPROCESS_QUALITY`` 决定）：
- fast：``PIL.ImageFilter.GaussianBlur(radius=1)``（零 OpenCV 调用）
- balanced：``cv2.bilateralFilter(d=9, sigmaColor=75, sigmaSpace=75)``
  边缘保留的快速平滑，~40ms/页（4000x4000）
- best：``cv2.fastNlMeansDenoising(h=7, templateWindowSize=7, searchWindowSize=21)``
  NL-Means 全搜索，~800ms/页（4000x4000），适合一次性精扫

实测性能（4000x4000 灰度）：
- fast       : ~70ms
- balanced   : ~40ms
- best       : ~800ms

注：fastNlMeansDenoising 要求 ``uint8`` 输入；float32 会被自动转换。
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageFilter


def _get_quality() -> str:
    return os.environ.get("BOOKCUT_PREPROCESS_QUALITY", "balanced").lower()


def _default_h(quality: str) -> int:
    return {"fast": 1, "balanced": 7, "best": 10}.get(quality, 7)


def denoise_from_array(
    arr: np.ndarray,
    h: int = 7,
    template_window_size: int = 7,
    search_window_size: int = 21,
    bilateral_diameter: int = 9,
    bilateral_sigma: float = 75.0,
    quality: str | None = None,
) -> np.ndarray:
    """降噪核心（v1.9+ A1：接受 ndarray）。

    Args:
        arr: 输入 ndarray（uint8 或 float32；fast/best 必须 uint8）。
        h: 滤波强度（亮度），仅 best（NL-Means）使用。
        template_window_size / search_window_size: 仅 best。
        bilateral_diameter / bilateral_sigma: 仅 balanced（cv2.bilateralFilter）。
        quality: 覆盖 ``BOOKCUT_PREPROCESS_QUALITY``。

    Returns:
        ndarray，dtype 与输入相同（fast 路径会 cast 回原 dtype）。
    """
    q = (quality or _get_quality()).lower()

    if q == "fast":
        # PIL GaussianBlur 是 uint8 only
        out = np.asarray(
            Image.fromarray(arr.astype(np.uint8), mode="L").filter(
                ImageFilter.GaussianBlur(radius=h)
            ),
            dtype=arr.dtype,
        )
        return out

    arr_u8 = arr.astype(np.uint8)
    if q == "balanced":
        # bilateralFilter：边缘保留 + 快（~40ms / 4000x4000）
        out_u8 = cv2.bilateralFilter(
            arr_u8, bilateral_diameter, bilateral_sigma, bilateral_sigma
        )
    else:  # best: NL-Means 全搜索
        out_u8 = cv2.fastNlMeansDenoising(
            arr_u8,
            None,
            h=h,
            templateWindowSize=template_window_size,
            searchWindowSize=search_window_size,
        )
    return out_u8.astype(arr.dtype)


def denoise(
    image: Image.Image,
    h: int | None = None,
    quality: str | None = None,
) -> Image.Image:
    """PIL Image wrapper：自动处理 L/RGB 模式。

    Args:
        image: 输入图像（任意模式，会先 ``convert("L")``）。
        h: 滤波强度；``None`` → 按 quality 默认。
        quality: fast/balanced/best；``None`` → 读环境变量。
    """
    q = (quality or _get_quality()).lower()
    if h is None:
        h = _default_h(q)

    if image.mode != "L":
        image = image.convert("L")
    arr = np.asarray(image, dtype=np.uint8)
    out = denoise_from_array(arr, h=h, quality=q)
    return Image.fromarray(out, mode="L")


def denoise_chain_token(token: str) -> tuple[str, float | None]:
    """解析 ``"denoise"`` 或 ``"denoise=10"`` → ``("denoise", h_or_None)``。"""
    token = token.strip()
    if "=" in token:
        name, val = token.split("=", 1)
        return name.strip(), float(val)
    return token, None
