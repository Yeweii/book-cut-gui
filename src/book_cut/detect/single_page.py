"""单页检测：识别扫描件是"双页跨页"还是"单页"。

古籍扫描中需要区分两种"空白"：

- **单页扫描**：另一边是扫描台/校色卡/色阶条（色值偏离纸色）。
- **跨页里的空白页**（衬页、版权页背面、章节扉页背面）：
  另一边是衬纸，色值 ≈ 纸色（纯白）。

算法：先比较两侧"墨迹"密度比；若一侧明显更空，
再检查空白侧的平均灰度：≥ ``paper_min_mean`` 视为纸 → 跨页；
否则视为扫描台/校色卡 → 单页。

墨迹阈值 = 中位数 - 30（自适应纸张色），下限 60。
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _to_gray_array(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.float32)


def _ink_mask(arr: np.ndarray) -> np.ndarray:
    """把图像二值化为"墨迹"：明显比中位数暗的像素。"""
    median = float(np.median(arr))
    threshold = max(median - 30.0, 60.0)
    return arr < threshold


def is_single_page_from_array(
    arr: np.ndarray,
    gutter_x: int,
    ratio_threshold: float = 0.1,
    paper_min_mean: float = 240.0,
) -> bool:
    """单页检测核心（v1.5+ A1：接受 ndarray）。

    ``is_single_page`` 的薄包装去掉 convert("L") 后，逻辑全在这里。
    """
    _h, w = arr.shape
    if w < 4 or gutter_x < 1 or gutter_x >= w - 1:
        return False

    mask = _ink_mask(arr)
    left = mask[:, :gutter_x]
    right = mask[:, gutter_x:]

    left_ratio = float(left.sum()) / left.size
    right_ratio = float(right.sum()) / right.size
    if max(left_ratio, right_ratio) <= 0:
        return False

    # 两侧墨迹接近 → 正常跨页
    if min(left_ratio, right_ratio) / max(left_ratio, right_ratio) >= ratio_threshold:
        return False

    # 一侧明显空。空白侧若是纸 → 跨页里的空白页（封面/衬页/版权背面）。
    if left_ratio < right_ratio:
        empty_mean = float(arr[:, :gutter_x].mean())
    else:
        empty_mean = float(arr[:, gutter_x:].mean())
    if empty_mean >= paper_min_mean:
        return False

    # 空白侧是扫描台/校色卡 → 真正的单页扫描
    return True


def is_single_page(
    image: Image.Image,
    gutter_x: int,
    ratio_threshold: float = 0.1,
    paper_min_mean: float = 240.0,
) -> bool:
    """检测图像是否为单页。

    v1.5+ A1：薄包装，convert("L") 后调 ``is_single_page_from_array``。

    Args:
        image: 输入图像。
        gutter_x: 已找到的中缝列坐标。
        ratio_threshold: 较小一侧 / 较大一侧 的最大比值；超过则视为单页。
            0.1 表示一边墨迹占比是另一边的 10% 以下。
        paper_min_mean: 空白侧平均灰度 ≥ 此值视为"纸"（衬纸 / 纸色），
            判定为跨页（cover/衬页情况）；< 此值视为扫描台 / 校色卡，
            判定为单页扫描。默认 240（衬纸白 ≈ 255、纸色中位 ≈ 217、
            灰扫描台 ≈ 180/200、校色卡彩色 18% 灰 ≈ 118）。

    Returns:
        True 表示单页扫描。
    """
    return is_single_page_from_array(
        _to_gray_array(image),
        gutter_x,
        ratio_threshold=ratio_threshold,
        paper_min_mean=paper_min_mean,
    )
