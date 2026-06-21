"""版框内裁：检测单页的外框线（版框），裁切到版框内部。

Canny/Hough 参数保持静态（几何检测，不受 paper color 影响）。
当版框检测失败时回退到 ``trim_margins``，trim 现在会接收 adaptive config
（来自 ``book_cut.detect.paper``）。

v1.5+ A1：``crop_to_border_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from book_cut.detect.paper import CropConfig


def _to_gray(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.uint8)


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    return Image.fromarray(arr_u8, mode="L")


def _detect_lines(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
    """返回 (竖线 x 列表, 横线 y 列表)。"""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=60,
        minLineLength=max(20, gray.shape[1] // 30),
        maxLineGap=8,
    )
    if lines is None:
        return None

    verticals: list[int] = []
    horizontals: list[int] = []

    for x1, y1, x2, y2 in lines[:, 0]:
        if abs(x1 - x2) < 3:
            verticals.append((x1 + x2) // 2)
        elif abs(y1 - y2) < 3:
            horizontals.append((y1 + y2) // 2)

    if not verticals or not horizontals:
        return None

    def cluster(values: list[int], tol: int = 5) -> list[int]:
        if not values:
            return []
        values = sorted(values)
        clusters: list[list[int]] = []
        cur = [values[0]]
        for v in values[1:]:
            if v - cur[-1] <= tol:
                cur.append(v)
            else:
                clusters.append(cur)
                cur = [v]
        clusters.append(cur)
        return [int(np.median(c)) for c in clusters]

    return cluster(verticals), cluster(horizontals)


def crop_to_border_from_array(
    arr: np.ndarray,
    padding: int = 5,
    config: CropConfig | None = None,
) -> Image.Image:
    """版框内裁核心（v1.5+ A1：接受 ndarray，返回 Image）。

    找不到版框时回退到 ``_trim_margins_from_array``（trim 的 from_array 变体），
    行为与 ``crop_to_border`` 完全一致。
    """
    h, w = arr.shape

    result = _detect_lines(arr)
    if result is None:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config)

    vs, hs = result
    if len(vs) < 2 or len(hs) < 2:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config)

    left = vs[0]
    right = vs[-1]
    top = hs[0]
    bottom = hs[-1]

    # 合理性检查：版框应包含图像主体
    if (right - left) < w * 0.2 or (bottom - top) < h * 0.2:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config)

    # 裁到版框内部（含 padding）
    cl = max(0, left + padding)
    ct = max(0, top + padding)
    cr = min(w, right - padding)
    cb = min(h, bottom - padding)

    if cr <= cl or cb <= ct:
        return _to_L_image(arr)

    return _to_L_image(arr[ct:cb, cl:cr])


def crop_to_border(
    image: Image.Image,
    padding: int = 5,
    config: CropConfig | None = None,
) -> Image.Image:
    """检测版框并裁切到版框内部。

    找不到版框时回退到 ``trim_margins``，并把 ``config`` 传过去（v1.3+）。

    v1.5+ A1：薄包装，调 ``crop_to_border_from_array``。

    Args:
        image: 单页图像（已经切分后）。
        padding: 距版框的内边距（像素）。
        config: 自适应裁切配置。``None`` = legacy 模式（传给 trim 时也是 legacy）。
            传给 trim 时 ``padding`` 仍可独立指定。
    """
    arr = _to_gray(image)
    return crop_to_border_from_array(arr, padding=padding, config=config)
