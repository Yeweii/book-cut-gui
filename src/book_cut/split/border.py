"""版框线切分：通过 Hough 直线检测找最大外接矩形，按矩形中心切分。

v1.5+ A1：``split_border_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _to_gray_bgr(image: Image.Image) -> np.ndarray:
    """PIL -> OpenCV BGR。"""
    if image.mode != "RGB":
        image = image.convert("RGB")
    arr = np.asarray(image)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _detect_outer_rectangle(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    """用 Hough 直线找最外侧版框。

    Returns:
        (left, top, right, bottom) 或 None。
    """
    edges = cv2.Canny(gray, 50, 150)
    # 用更细的线段，便于古籍中可能较短的直线
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(20, gray.shape[1] // 20),
        maxLineGap=10,
    )
    if lines is None:
        return None

    verticals: list[int] = []
    horizontals: list[int] = []

    for x1, y1, x2, y2 in lines[:, 0]:
        if abs(x1 - x2) < 3:  # 竖线
            verticals.append((x1 + x2) // 2)
        elif abs(y1 - y2) < 3:  # 横线
            horizontals.append((y1 + y2) // 2)

    if not verticals or not horizontals:
        return None

    # 聚类：合并相邻 ±5 像素的同类直线
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
        # 取每簇的中位数
        return [int(np.median(c)) for c in clusters]

    vs = cluster(verticals)
    hs = cluster(horizontals)

    if len(vs) < 2 or len(hs) < 2:
        return None

    h_img, w_img = gray.shape
    # 版框一般靠内侧；取最靠左和最靠右的"较显著"竖线
    # 简化：取 x 最小与 x 最大的两簇
    left = vs[0]
    right = vs[-1]
    top = hs[0]
    bottom = hs[-1]

    # 合理性：版框应包含图像主体（不能太小）
    if (right - left) < w_img * 0.3 or (bottom - top) < h_img * 0.3:
        return None

    return (left, top, right, bottom)


def find_border_split(image: Image.Image) -> int | None:
    """返回版框水平中心切分线 x 坐标（None 表示未找到版框）。"""
    gray = _to_gray_bgr(image)
    rect = _detect_outer_rectangle(gray)
    if rect is None:
        return None
    left, _top, right, _bottom = rect
    return (left + right) // 2


def find_border_split_from_array(arr: np.ndarray) -> int | None:
    """版框 split 核心（v1.5+ A1：接受 ndarray）。"""
    rect = _detect_outer_rectangle(arr)
    if rect is None:
        return None
    left, _top, right, _bottom = rect
    return (left + right) // 2


def split_border_from_array(arr: np.ndarray) -> list[np.ndarray]:
    """版框切分核心（v1.5+ A1：接受 ndarray，返回 list[ndarray]）。

    找不到版框时 fallback 到对半切 ndarray 版。
    """
    from book_cut.split.half import split_half_from_array

    w = arr.shape[1]
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    x = find_border_split_from_array(arr)
    if x is None or not (1 <= x <= w - 1):
        return split_half_from_array(arr)
    return [arr[:, :x], arr[:, x:]]


def split_border(image: Image.Image) -> list[Image.Image]:
    """按版框水平中心切分；找不到版框时 fallback 到对半切。返回 [left, right]。

    v1.5+ A1：薄包装，调 ``split_border_from_array``，结果包回 Image。
    """
    w = image.size[0]
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    arr = _to_gray_bgr(image)
    sub_arrs = split_border_from_array(arr)
    return [Image.fromarray(sub, mode="L") for sub in sub_arrs]
