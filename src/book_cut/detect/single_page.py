"""单页检测：识别扫描件是"双页跨页"还是"单页"。

古籍扫描中常见两种异常：
- 封面、衬页、版权页往往是单页
- 校色卡/色阶条也是单页放在一侧
- 装订/扫描瑕疵导致一边几乎全白

算法：找到候选的中缝列后，比较两侧"墨迹"密度比。
若较小的一侧墨迹占比 < 较大一侧的 threshold 倍（且绝对值 < 0.005），
则判定为单页扫描。墨迹阈值 = 中位数 - 30（自适应纸张色）。
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


def is_single_page(image: Image.Image, gutter_x: int, ratio_threshold: float = 0.1) -> bool:
    """检测图像是否为单页。

    Args:
        image: 输入图像。
        gutter_x: 已找到的中缝列坐标。
        ratio_threshold: 较小一侧 / 较大一侧 的最大比值；超过则视为单页。
            0.1 表示一边墨迹占比是另一边的 10% 以下。

    Returns:
        True 表示单页扫描。
    """
    arr = _to_gray_array(image)
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

    return min(left_ratio, right_ratio) / max(left_ratio, right_ratio) < ratio_threshold
