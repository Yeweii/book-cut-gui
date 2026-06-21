"""中缝检测切分：通过列投影找最亮列作为切分点。

适用场景：扫描平整、装订线为白色或较浅的输入（绝大多数平板扫描）。
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _to_gray_array(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.float32)


def find_gutter_column(
    image: Image.Image,
    search_range: float = 0.4,
    min_white_value: float = 220.0,
    min_run_width: int = 10,
) -> int:
    """寻找中缝列。

    算法：
    1. 转灰度，计算每列均值。
    2. 在中心 search_range 范围内，找出"最长连续亮列"的中心。
       中缝是无内容区，列均值 ≥ 阈值且连续成段；与外围散点白边区分。

    Args:
        image: 输入图像。
        search_range: 中心搜索范围（占宽度的比例）。
        min_white_value: 视为"亮列"的最低列均值。
        min_run_width: 中缝段至少多宽（像素），过滤偶发白列。

    Returns:
        切分列 x 坐标。
    """
    arr = _to_gray_array(image)
    _h, w = arr.shape
    col_means = arr.mean(axis=0)

    center = w // 2
    half_window = int(w * search_range / 2)
    lo = max(0, center - half_window)
    hi = min(w, center + half_window)

    is_white = col_means[lo:hi] >= min_white_value

    # 找最长连续 True 段
    best_start, best_len = -1, 0
    cur_start, cur_len = -1, 0
    for i, v in enumerate(is_white):
        if v:
            if cur_start == -1:
                cur_start, cur_len = i, 1
            else:
                cur_len += 1
        else:
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
            cur_start, cur_len = -1, 0
    if cur_len > best_len:
        best_start, best_len = cur_start, cur_len

    if best_len < min_run_width:
        # 兜底：返回搜索范围中点
        return center

    return lo + best_start + best_len // 2


def split_gutter(
    image: Image.Image,
    search_range: float = 0.4,
    auto_single_page: bool = True,
) -> list[Image.Image]:
    """按中缝列切分；检测到单页时直接返回整图（列表长度为 1）。

    Args:
        image: 输入图像。
        search_range: 中缝搜索范围（占宽比例）。
        auto_single_page: True 时启用单页自动检测。

    Returns:
        1 张图（单页）或 2 张图（双页跨页）。
    """
    w = image.size[0]
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    x = find_gutter_column(image, search_range=search_range)
    x = max(1, min(w - 1, x))

    if auto_single_page:
        from book_cut.detect.single_page import is_single_page

        if is_single_page(image, gutter_x=x):
            return [image.copy()]

    return [image.crop((0, 0, x, image.size[1])), image.crop((x, 0, w, image.size[1]))]
