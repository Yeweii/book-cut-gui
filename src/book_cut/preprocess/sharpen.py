"""锐化（v1.9+）：unsharp mask。

三档实现（由 ``BOOKCUT_PREPROCESS_QUALITY`` 决定）：
- fast：``PIL.ImageFilter.SHARPEN``（3×3 锐化核，零额外依赖）
- balanced：``cv2.GaussianBlur`` + ``cv2.addWeighted``（amount=1.5, radius=1.0）
- best：同 balanced，amount=2.0, radius=1.5

操作数：
- 输入 ``Image`` / ``ndarray(uint8 | float32)``
- 输出保持原 dtype / mode
"""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageFilter


def _get_quality() -> str:
    return os.environ.get("BOOKCUT_PREPROCESS_QUALITY", "balanced").lower()


def _default_amount(quality: str) -> float:
    return {"fast": 1.0, "balanced": 1.5, "best": 2.0}.get(quality, 1.5)


def _default_radius(quality: str) -> float:
    return {"fast": 0.0, "balanced": 1.0, "best": 1.5}.get(quality, 1.0)


def sharpen_from_array(
    arr: np.ndarray,
    amount: float = 1.5,
    radius: float = 1.0,
    quality: str | None = None,
) -> np.ndarray:
    """锐化核心（v1.9+ A1：接受 ndarray）。

    Args:
        arr: 输入 ndarray（uint8 或 float32；2D 灰度或 3D 彩色）。
        amount: 锐化强度（0=原图，1=典型 unsharp mask，2=强）。
        radius: 高斯模糊半径（仅 balanced/best；fast 走 PIL 核）。
        quality: 覆盖 ``BOOKCUT_PREPROCESS_QUALITY``（fast/balanced/best）。

    Returns:
        ndarray，dtype 与输入相同。
    """
    q = (quality or _get_quality()).lower()

    if q == "fast":
        # PIL SHARPEN 是 uint8 only；结果转回原 dtype
        out = np.asarray(
            Image.fromarray(arr.astype(np.uint8), mode="L").filter(ImageFilter.SHARPEN),
            dtype=arr.dtype,
        )
        return out

    # balanced/best：unsharp mask = 原图 + amount * (原图 - 高斯模糊)
    blurred = cv2.GaussianBlur(arr, (0, 0), radius)
    return cv2.addWeighted(arr, 1.0 + amount, blurred, -amount, 0)


def sharpen(
    image: Image.Image,
    amount: float | None = None,
    radius: float | None = None,
    quality: str | None = None,
) -> Image.Image:
    """PIL Image wrapper：自动处理 L/RGB 模式。

    Args:
        image: 输入图像（任意模式，会先 ``convert("L")``）。
        amount: 锐化强度；``None`` → 按 quality 默认。
        radius: 高斯模糊半径；``None`` → 按 quality 默认。
        quality: fast/balanced/best；``None`` → 读环境变量。
    """
    q = (quality or _get_quality()).lower()
    if amount is None:
        amount = _default_amount(q)
    if radius is None:
        radius = _default_radius(q)

    if image.mode != "L":
        image = image.convert("L")
    arr = np.asarray(image, dtype=np.uint8)
    out = sharpen_from_array(arr, amount=amount, radius=radius, quality=q)
    return Image.fromarray(out, mode="L")


def sharpen_chain_token(token: str) -> tuple[str, float | None]:
    """解析 ``"sharpen"`` 或 ``"sharpen=1.5"`` → ``("sharpen", amount_or_None)``。

    ``None`` = 用 quality 默认值；显式数字 = 覆盖默认。
    """
    token = token.strip()
    if "=" in token:
        name, val = token.split("=", 1)
        return name.strip(), float(val)
    return token, None
