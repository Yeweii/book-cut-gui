"""中缝检测切分：通过列投影找最亮列作为切分点。

适用场景：扫描平整、装订线为白色或较浅的输入（绝大多数平板扫描）。

v1.5+ A1：``split_gutter_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
v1.6+ A线：列白度判据由 ``mean ≥ 220`` 升级为 **p95 ≥ 230 AND mean ≥ 220** 双判据，
        抗古籍稀疏文字列（每列 1-2 暗像素）被误认作白列。默认参数同时收紧：
        ``search_range 0.4 → 0.2``（只搜中心 ±10%）、``min_white_value 220 → 230``、
        ``min_run_width 10 → 20``（要求更宽白段）。
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
    search_range: float = 0.2,
    min_white_value: float = 230.0,
    min_run_width: int = 20,
) -> int:
    """寻找中缝列。

    算法（v1.6+）：
    1. 转灰度，计算每列 p95 + mean。
    2. 在中心 ``search_range`` 范围内，列同时满足 ``p95 ≥ min_white_value`` AND
       ``mean ≥ 220`` 视为白列。找"最长连续白列"的中心。
    3. 中缝是无内容区，白列连续成段；与外围散点白边区分。

    双判据关键意义（详见 ``detect.paper._column_is_white``）：
    纯白列 p95=255；稀疏文字列 p95<200（被 1-2 个暗像素拉低）→ 不被误认。

    Args:
        image: 输入图像。
        search_range: 中心搜索范围（占宽度的比例）。v1.6+ 默认 0.2（中心 ±10%）。
        min_white_value: p95 阈值（默认 230）。mean 阈值固定 220。
        min_run_width: 中缝段至少多宽（像素），过滤偶发白列。v1.6+ 默认 20。

    Returns:
        切分列 x 坐标。
    """
    arr = _to_gray_array(image)
    return find_gutter_column_from_array(
        arr,
        search_range=search_range,
        min_white_value=min_white_value,
        min_run_width=min_run_width,
    )


def find_gutter_column_from_array(
    arr: np.ndarray,
    search_range: float = 0.2,
    min_white_value: float = 230.0,
    min_run_width: int = 20,
) -> int:
    """中缝列核心（v1.5+ A1：接受 ndarray；v1.6+ p95+mean 双判据）。"""
    from book_cut.detect.paper import _column_is_white

    _h, w = arr.shape

    center = w // 2
    half_window = int(w * search_range / 2)
    lo = max(0, center - half_window)
    hi = min(w, center + half_window)

    # v1.6+：双判据（p95 + mean）。mean 阈值固定 220，与 v1.3 ``min_white_value`` 对齐。
    is_white = np.array(
        [_column_is_white(arr[:, x], min_p95=min_white_value, min_mean=220.0) for x in range(lo, hi)]
    )

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


def split_gutter_from_array(
    arr: np.ndarray,
    search_range: float = 0.2,
    auto_single_page: bool = True,
) -> list[np.ndarray]:
    """中缝切分核心（v1.5+ A1：接受 ndarray，返回 list[ndarray]）。

    pipeline 热路径：输入 arr，输出两个子 ndarray。下游 crop/binarize 继续在 arr 上跑。
    v1.6+ 默认 ``search_range=0.2``、``min_white_value=230``、``min_run_width=20``。
    """
    w = arr.shape[1]
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    x = find_gutter_column_from_array(
        arr,
        search_range=search_range,
        min_white_value=230.0,
        min_run_width=20,
    )
    x = max(1, min(w - 1, x))

    if auto_single_page:
        from book_cut.detect.single_page import is_single_page_from_array

        if is_single_page_from_array(arr, gutter_x=x):
            return [arr]

    return [arr[:, :x], arr[:, x:]]


def split_gutter(
    image: Image.Image,
    search_range: float = 0.2,
    auto_single_page: bool = True,
) -> list[Image.Image]:
    """按中缝列切分；检测到单页时直接返回整图（列表长度为 1）。

    v1.5+ A1：薄包装，convert("L") 后调 ``split_gutter_from_array``，结果包回 Image。
    v1.6+ 默认 ``search_range=0.2``。

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
    arr = _to_gray_array(image)
    sub_arrs = split_gutter_from_array(
        arr, search_range=search_range, auto_single_page=auto_single_page
    )
    # 包回 L mode Image（保留与原公共 API 行为一致）
    return [Image.fromarray(sub, mode="L") for sub in sub_arrs]
