"""detect 子包共享工具（v1.6+ C2）。

集中维护：
- ``to_gray_array`` / ``to_gray``：PIL Image → 灰度 ndarray
- ``to_L_image``：ndarray → L mode PIL Image
- ``adaptive_padding``：按图像尺寸算 padding

原散落在 paper.py / trim.py / border.py / binarize.py / deskew.py / single_page.py / gutter.py。
C2 把 paper.py 和 trim.py 的重复公式合并到本模块；其余模块暂不动（避免大爆炸 PR）。
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def to_gray_array(image: Image.Image, dtype: type = np.uint8) -> np.ndarray:
    """PIL Image → 灰度 ndarray。

    非 L 模式自动 ``convert("L")``。

    Args:
        image: PIL 图像（任意 mode）。
        dtype: 输出 dtype，默认 ``uint8``（灰度图最常用）。
            ``float32`` 用于 Sauvola 这类需要浮点阈值的算法。

    Returns:
        灰度 ndarray。
    """
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=dtype)


def to_L_image(arr_u8: np.ndarray) -> Image.Image:
    """uint8 ndarray → L mode PIL Image。

    Args:
        arr_u8: uint8 ndarray（典型为二值图或裁切后的灰度图）。

    Returns:
        L mode PIL Image。
    """
    return Image.fromarray(arr_u8, mode="L")


def adaptive_padding(h: int, w: int) -> int:
    """按图像尺寸算自适应 padding。

    公式：``max(int(min(h, w) * 0.02), 5)``，clamp ≤ 30。
    - 700px 短边 → 14px
    - 1500px → 30px (cap)
    - 4000px → 30px (cap)
    - 小于 250px → 5px (floor)

    Args:
        h: 图像高。
        w: 图像宽。

    Returns:
        像素 padding。
    """
    base = int(min(h, w) * 0.02)
    return max(5, min(30, base))