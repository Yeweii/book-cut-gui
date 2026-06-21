"""共享 Hough 直线检测工具（v1.5+ C1）。

提供：
- ``canny_edges(gray)``：Canny 边检测
- ``detect_lines(gray, ...)``：Canny + HoughLinesP
- ``cluster_lines(lines)``：合并相邻同向线段，返回 (vs, hs)

3 个 caller（deskew / split_border / crop_border）共用，统一参数。
参数差异通过 ``detect_lines(..., threshold=, min_length_factor=, max_gap=)`` 显式传。
"""

from __future__ import annotations

import cv2
import numpy as np

# 各 caller 的 Hough 参数 preset（v1.5+ C1：集中维护）
HOUGH_PRESET_DESKEW: dict[str, int] = {
    "threshold": 80,
    "min_length_factor": 20,
    "max_gap": 10,
}
HOUGH_PRESET_SPLIT_BORDER: dict[str, int] = {
    "threshold": 80,
    "min_length_factor": 20,
    "max_gap": 10,
}
HOUGH_PRESET_CROP_BORDER: dict[str, int] = {
    "threshold": 60,
    "min_length_factor": 30,
    "max_gap": 8,
}


def canny_edges(gray: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    """Canny 边检测（共享）。"""
    return cv2.Canny(gray, low, high)


def detect_lines(
    gray: np.ndarray,
    *,
    threshold: int = 80,
    min_length_factor: int = 20,
    max_gap: int = 10,
) -> list[tuple[int, int, int, int]] | None:
    """Canny + HoughLinesP，返回 ``[(x1,y1,x2,y2), ...]`` 或 None。

    Args:
        gray: 单通道 uint8 图。
        threshold: Hough 累加器阈值（线段投票数）。
        min_length_factor: 最短线长 = ``max(20, w // min_length_factor)``。
        max_gap: 同一直线允许的最大间断。
    """
    edges = canny_edges(gray)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=threshold,
        minLineLength=max(20, gray.shape[1] // min_length_factor),
        maxLineGap=max_gap,
    )
    if lines is None:
        return None
    return [(int(x1), int(y1), int(x2), int(y2)) for x1, y1, x2, y2 in lines[:, 0]]


def cluster_lines(
    lines: list[tuple[int, int, int, int]],
    tol: int = 5,
) -> tuple[list[int], list[int]]:
    """合并相邻同向线段，返回 ``(竖线 x 列表, 横线 y 列表)``。

    每簇取 x（或 y）中位数作为代表。
    """
    verticals: list[int] = []
    horizontals: list[int] = []
    for x1, y1, x2, y2 in lines:
        if abs(x1 - x2) < 3:
            verticals.append((x1 + x2) // 2)
        elif abs(y1 - y2) < 3:
            horizontals.append((y1 + y2) // 2)

    def _cluster(values: list[int], tol: int = tol) -> list[int]:
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

    return _cluster(verticals), _cluster(horizontals)
