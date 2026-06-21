"""白边裁切：从四个方向找到第一个非白像素，向内裁掉。"""

from __future__ import annotations

import numpy as np
from PIL import Image


def trim_margins(
    image: Image.Image,
    threshold: int = 240,
    padding: int = 10,
) -> Image.Image:
    """去掉图片四周的白边。

    策略：扫描每行/列，只要存在一个"非白"像素（值 < threshold）就视为
    "有内容"行/列。取首/末"有内容"行/列为裁切边界，外加 padding。

    Args:
        image: 输入图像。
        threshold: 灰度值 < threshold 视为有内容。
        padding: 保留的最小边距（像素），避免贴边。
    """
    if image.mode != "L":
        gray = image.convert("L")
    else:
        gray = image
    arr = np.asarray(gray)
    h, w = arr.shape

    row_has_content = (arr < threshold).any(axis=1)
    col_has_content = (arr < threshold).any(axis=0)

    rows_idx = np.where(row_has_content)[0]
    cols_idx = np.where(col_has_content)[0]

    if len(rows_idx) == 0 or len(cols_idx) == 0:
        # 全白/全非白：原图返回
        return image

    top = int(rows_idx[0])
    bottom = int(rows_idx[-1])
    left = int(cols_idx[0])
    right = int(cols_idx[-1])

    # 应用 padding（不超出原图）
    top = max(0, top - padding)
    left = max(0, left - padding)
    bottom = min(h - 1, bottom + padding)
    right = min(w - 1, right + padding)

    # 至少留 1px
    if bottom <= top or right <= left:
        return image

    return image.crop((left, top, right + 1, bottom + 1))
