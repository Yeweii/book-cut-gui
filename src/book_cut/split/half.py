"""对半切：固定 w//2，支持 offset 微调。

v1.5+ A1：``split_half_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def split_half_from_array(arr: np.ndarray, offset: int = 0) -> list[np.ndarray]:
    """对半切核心（v1.5+ A1：接受 ndarray，返回 list[ndarray]）。"""
    w = arr.shape[1]
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    mid = max(1, min(w - 1, w // 2 + offset))
    return [arr[:, :mid], arr[:, mid:]]


def split_half(image: Image.Image, offset: int = 0) -> list[Image.Image]:
    """在 width//2 + offset 处切分，返回 [left, right]。

    v1.5+ A1：薄包装，调 ``split_half_from_array``，结果包回 Image。
    """
    arr = np.asarray(image.convert("L"))
    sub_arrs = split_half_from_array(arr, offset=offset)
    return [Image.fromarray(sub, mode="L") for sub in sub_arrs]
