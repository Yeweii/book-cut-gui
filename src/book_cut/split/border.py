"""版框线切分：通过 Hough 直线检测找最大外接矩形，按矩形中心切分。

v1.5+ A1：``split_border_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
v1.6+ A3：``split_border_with_rects_from_array`` 额外返回每页的版框 rect
（``page_rects``），供 ``crop_to_border_from_array(page_rect=...)`` 复用 Hough 结果，
省一次 Hough + Canny + cluster（约 4ms/页）。
"""

from __future__ import annotations

from dataclasses import dataclass

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

    v1.5+ C1：调共享 ``detect_lines`` + ``cluster_lines``，参数与 v1.4 等价。

    Returns:
        (left, top, right, bottom) 或 None。
    """
    from book_cut.detect._hough import HOUGH_PRESET_SPLIT_BORDER, cluster_lines, detect_lines

    lines = detect_lines(gray, **HOUGH_PRESET_SPLIT_BORDER)
    if lines is None:
        return None

    vs, hs = cluster_lines(lines)
    if len(vs) < 2 or len(hs) < 2:
        return None

    h_img, w_img = gray.shape
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


@dataclass
class SplitBorderResult:
    """v1.6+ A3：split_border 返回切分结果 + 每页的版框 rect。

    Attributes:
        sub_arrays: 切分后的子图 ndarray 列表。
        page_rects: 每子图对应的 ``(left, top, right, bottom)`` 版框 rect
            （**子图坐标系**，可直接喂给 ``crop_to_border_from_array(page_rect=...)``）。
            ``None`` 表示 fallback（未找到版框 → 对半切），crop 应自己跑 Hough。
    """

    sub_arrays: list[np.ndarray]
    page_rects: list[tuple[int, int, int, int] | None]


def _derive_page_rects(
    vs: list[int],
    hs: list[int],
    x: int,
    h_img: int,
    w_img: int,
) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    """v1.6+ A3：从 split_border 一次 Hough 的 cluster 结果推导每页版框 rect。

    关键观察：cluster_lines 给的是所有竖/横线簇，排序后含外侧 + 内侧。
    - 左页的右框 = ``vs`` 中 < x 的最大 x（最靠近 split 线）
    - 右页的左框 = ``vs`` 中 > x 的最小 x（最靠近 split 线）

    Returns:
        ``(left_page_rect, right_page_rect)``（子图坐标系），任一为 None 表示
        退化（宽度太窄或 degenerate），crop 应自跑 Hough。
    """
    top, bottom = hs[0], hs[-1]
    outer_left, outer_right = vs[0], vs[-1]

    # 左页右框：vs 中 < x 的最大 x（找不到则用 outer_left → degenerate）
    left_right_candidates = [v for v in vs if v < x]
    left_right = max(left_right_candidates) if left_right_candidates else outer_left
    # 右页左框：vs 中 > x 的最小 x（找不到则用 outer_right → degenerate）
    right_left_candidates = [v for v in vs if v > x]
    right_left = min(right_left_candidates) if right_left_candidates else outer_right

    # 退化检查：宽/高过小 → 返回 None
    # 用子图宽度（不是全图宽度）做阈值 — 否则双页扫描里小版框可能
    # "宽于"全图 5% 但仍远小于其所在子图（典型：古籍版框只占半页中央）。
    sub_w_left = max(1, x)  # 左子图宽度
    sub_w_right = max(1, w_img - x)  # 右子图宽度
    min_dim_left = max(20, int(sub_w_left * 0.2))
    min_dim_right = max(20, int(sub_w_right * 0.2))
    # 左页 rect（原图坐标 = 左子图坐标）
    if (
        left_right - outer_left < min_dim_left
        or bottom - top < min_dim_left
        # 兜底：rect 太窄（< 50% 子图宽）说明 Hough 在全图上漏掉了真正的
        # 版框边（典型：古籍靠页边的细线在全图 cluster 里被并入邻居），
        # 此时用 page_rect 反而比 crop 自跑 Hough 差 → 让 crop 走原路径。
        or left_right - outer_left < sub_w_left * 0.5
    ):
        left_rect = None
    else:
        left_rect = (outer_left, top, left_right, bottom)
    # 右页 rect（需平移到右子图坐标）
    if (
        outer_right - right_left < min_dim_right
        or bottom - top < min_dim_right
        or outer_right - right_left < sub_w_right * 0.5
    ):
        right_rect = None
    else:
        right_rect = (right_left - x, top, outer_right - x, bottom)

    return left_rect, right_rect


def split_border_with_rects_from_array(arr: np.ndarray) -> SplitBorderResult:
    """v1.6+ A3：版框切分 + 推导每页版框 rect（crop 复用 Hough 结果）。

    与 ``split_border_from_array`` 区别：
    - 跑一次 Hough（不重复 split + crop 各跑一次）
    - 返回 ``SplitBorderResult.sub_arrays`` + ``page_rects``
    - 找不到版框 / 退化时 ``page_rects`` = ``[None, None]``

    pipeline 在 ``--split border --crop border`` 时用本函数省一次 Hough。
    """
    from book_cut.detect._hough import (
        HOUGH_PRESET_CROP_BORDER,
        cluster_lines,
        detect_lines,
    )
    from book_cut.split.half import split_half_from_array

    h_img, w_img = arr.shape
    if w_img < 2:
        raise ValueError(f"图像宽度过小: {w_img}")

    # v1.6+ A3：用 CROP preset（threshold=60）而非 SPLIT preset（threshold=80）。
    # 原因：A3 跑一次 Hough 同时给 split（找外框）和 crop（找每页内框）用。
    # SPLIT 太严会漏掉每页的细版框边 → page_rect 比 crop 自跑 Hough 窄。
    # CROP 较松，能同时找到外框 + 每页内框，且 outer left/right 还是最外侧。
    lines = detect_lines(arr, **HOUGH_PRESET_CROP_BORDER)
    if lines is None:
        return SplitBorderResult(
            sub_arrays=split_half_from_array(arr),
            page_rects=[None, None],
        )

    vs, hs = cluster_lines(lines)
    if len(vs) < 2 or len(hs) < 2:
        return SplitBorderResult(
            sub_arrays=split_half_from_array(arr),
            page_rects=[None, None],
        )

    outer_left, top, outer_right, bottom = vs[0], hs[0], vs[-1], hs[-1]
    # 合理性：外框应包含主体（与 _detect_outer_rectangle 相同）
    if (outer_right - outer_left) < w_img * 0.3 or (bottom - top) < h_img * 0.3:
        return SplitBorderResult(
            sub_arrays=split_half_from_array(arr),
            page_rects=[None, None],
        )

    x = (outer_left + outer_right) // 2
    x = max(1, min(w_img - 1, x))

    # 推导每页 rect（在子图坐标系）
    left_rect, right_rect = _derive_page_rects(vs, hs, x, h_img, w_img)

    return SplitBorderResult(
        sub_arrays=[arr[:, :x], arr[:, x:]],
        page_rects=[left_rect, right_rect],
    )


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
