"""CLAHE 对比度增强（v1.9+）：局部自适应直方图均衡。

解决古籍泛黄纸 / 光照不均导致的墨迹对比不足。

三档实现：
- fast：等价 no-op（返回原图；PIL 无 CLAHE，保持 fast 档零额外延迟）
- balanced：``cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))``
- best：``cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))``

仅在灰度（L 模式）上有意义；输入非 L 时先 ``convert("L")``。
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image


def _get_quality() -> str:
    return os.environ.get("BOOKCUT_PREPROCESS_QUALITY", "balanced").lower()


def _default_clip(quality: str) -> float:
    return {"fast": 1.0, "balanced": 2.0, "best": 3.0}.get(quality, 2.0)


def _clahe_object(quality: str, clip: float) -> cv2.CLAHE:
    """构造 CLAHE 对象（balanced/best；fast 直接 no-op 不调此函数）。"""
    return cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))


def clahe_from_array(
    arr: np.ndarray,
    clip: float = 2.0,
    quality: str | None = None,
) -> np.ndarray:
    """CLAHE 核心（v1.9+ A1：接受 ndarray）。

    Args:
        arr: 输入 ndarray（uint8 或 float32；2D 灰度）。
        clip: 对比度限制（默认 2.0；古籍泛黄常用 2.0~3.0）。
        quality: 覆盖 ``BOOKCUT_PREPROCESS_QUALITY``。

    Returns:
        ndarray，dtype 与输入相同。
    """
    q = (quality or _get_quality()).lower()

    if q == "fast":
        # fast 档 no-op（保持 v1.8 行为，零延迟）
        return arr

    arr_u8 = arr.astype(np.uint8)
    cl = _clahe_object(q, clip).apply(arr_u8)
    return cl.astype(arr.dtype)


def clahe(
    image: Image.Image,
    clip: float | None = None,
    quality: str | None = None,
) -> Image.Image:
    """PIL Image wrapper：自动处理 L/RGB 模式。

    Args:
        image: 输入图像（任意模式，会先 ``convert("L")``）。
        clip: 对比度限制；``None`` → 按 quality 默认。
        quality: fast/balanced/best；``None`` → 读环境变量。
    """
    q = (quality or _get_quality()).lower()
    if clip is None:
        clip = _default_clip(q)

    if image.mode != "L":
        image = image.convert("L")
    arr = np.asarray(image, dtype=np.uint8)
    out = clahe_from_array(arr, clip=clip, quality=q)
    return Image.fromarray(out, mode="L")


def clahe_chain_token(token: str) -> tuple[str, float | None]:
    """解析 ``"clahe"`` 或 ``"clahe=3.0"`` → ``("clahe", clip_or_None)``。"""
    token = token.strip()
    if "=" in token:
        name, val = token.split("=", 1)
        return name.strip(), float(val)
    return token, None
