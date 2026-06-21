"""白边裁切：从四个方向找到第一个非白像素，向内裁掉。

支持两种模式：
- **legacy 模式**（``config=None`` 或显式 ``threshold``/``padding``）：
  用硬编码 ``threshold=240, padding=10``，"任一非白像素"判内容。
  与 v1.1 行为完全一致，向后兼容。
- **adaptive 模式**（传 ``config=CropConfig(...)``）：
  用 ``config.ink_threshold`` 作墨迹阈值，``config.padding``（或按尺寸自适应）作 padding，
  ``config.min_edge_ink`` 作边缘"有内容"判定（默认 3 px，杀单像素 JPEG 噪声）。

v1.5+ A1：``_trim_margins_from_array`` 私有变体接受 ndarray，pipeline 用它避免重复 ``convert("L")``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from book_cut.detect.paper import CropConfig


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    """ndarray (uint8) → L mode PIL Image（trim/binarize 共用）。"""
    return Image.fromarray(arr_u8, mode="L")


def _trim_margins_from_array(
    arr: np.ndarray,
    *,
    config: CropConfig | None = None,
    threshold: int | None = None,
    padding: int | None = None,
) -> Image.Image:
    """trim 核心逻辑（v1.5+ A1：接受 ndarray，返回 Image）。

    公共函数 ``trim_margins`` 的薄包装去掉后，逻辑全在这里。
    pipeline 在主循环一次 ``convert("L")`` 后直接调本函数，跳过重复转换。
    """
    h, w = arr.shape

    # 选择模式：config 优先；否则用 legacy 显式参数；再否则默认 240/10
    if config is not None:
        ink_thr = config.ink_threshold
        pad = config.padding if config.padding is not None else _default_adaptive_padding(h, w)
        min_ink = max(1, config.min_edge_ink)
    else:
        ink_thr = threshold if threshold is not None else 240
        pad = padding if padding is not None else 10
        # legacy 模式 = "任一非白像素" = sum >= 1
        min_ink = 1

    ink_mask = arr < ink_thr
    if min_ink <= 1:
        # 快速路径：legacy 行为
        row_has_content = ink_mask.any(axis=1)
        col_has_content = ink_mask.any(axis=0)
    else:
        row_has_content = ink_mask.sum(axis=1) >= min_ink
        col_has_content = ink_mask.sum(axis=0) >= min_ink

    rows_idx = np.where(row_has_content)[0]
    cols_idx = np.where(col_has_content)[0]

    if len(rows_idx) == 0 or len(cols_idx) == 0:
        # 全白/全非白：原图返回（重建 Image）
        return _to_L_image(arr)

    top = int(rows_idx[0])
    bottom = int(rows_idx[-1])
    left = int(cols_idx[0])
    right = int(cols_idx[-1])

    # 应用 padding（不超出原图）
    top = max(0, top - pad)
    left = max(0, left - pad)
    bottom = min(h - 1, bottom + pad)
    right = min(w - 1, right + pad)

    # 至少留 1px
    if bottom <= top or right <= left:
        return _to_L_image(arr)

    return _to_L_image(arr[top : bottom + 1, left : right + 1])


def trim_margins(
    image: Image.Image,
    threshold: int | None = None,
    padding: int | None = None,
    config: CropConfig | None = None,
) -> Image.Image:
    """去掉图片四周的白边。

    策略：扫描每行/列，把"有内容"行/列的首末位置作为裁切边界，外加 padding。

    v1.5+ A1：薄包装，convert("L") 后调 ``_trim_margins_from_array``。

    Args:
        image: 输入图像。
        threshold: 灰度值 < threshold 视为有内容（legacy）。
            缺省 = 240。``config`` 不为 None 时忽略。
        padding: 保留的最小边距（像素，legacy）。缺省 = 10。
            ``config`` 不为 None 时忽略（用 config.padding / 自适应）。
        config: 自适应裁切配置。``None`` = legacy 模式。

    Returns:
        裁切后的图像。
    """
    if image.mode != "L":
        gray = image.convert("L")
    else:
        gray = image
    arr = np.asarray(gray)
    return _trim_margins_from_array(
        arr, config=config, threshold=threshold, padding=padding
    )


def _default_adaptive_padding(h: int, w: int) -> int:
    """trim 内部用的 padding 兜底（避免循环 import paper 模块）。

    与 ``detect.paper.adaptive_padding`` 公式一致：
    ``max(int(min(h, w) * 0.02), 5)``，clamp ≤ 30。
    """
    base = int(min(h, w) * 0.02)
    return max(5, min(30, base))
