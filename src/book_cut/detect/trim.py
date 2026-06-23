"""白边裁切：从四个方向找到第一个非白像素，向内裁掉。

支持两种模式：
- **legacy 模式**（``config=None`` 或显式 ``threshold``/``padding``）：
  用硬编码 ``threshold=240, padding=10``，"任一非白像素"判内容。
  与 v1.1 行为完全一致，向后兼容。
- **adaptive 模式**（传 ``config=CropConfig(...)``）：
  用 ``config.ink_threshold`` 作墨迹阈值，``config.padding``（或按尺寸自适应）作 padding，
  ``config.min_edge_ink`` 作边缘"有内容"判定（默认 3 px，杀单像素 JPEG 噪声）。

v1.5+ A1：``_trim_margins_from_array`` 私有变体接受 ndarray，pipeline 用它避免重复 ``convert("L")``。
v1.6+ B线：
- **MORPH_OPEN 抗尘点**：``cv2.morphologyEx(MORPH_OPEN, 3x3)`` 清 1-3 px 孤立点
- **safety margin 贴边保护**：内容距图边 < ``max(5, min(h,w)*0.01)`` → 不裁
- **min_ink 统一**：legacy `1` → `≥ 3`（与 adaptive 对齐），杀 JPEG 噪声
- **CLI opt-out**：``--no-morph`` 关闭形态学（古籍飞白/极小字可见时用）

v1.6+ C2：``_default_adaptive_padding`` 重复公式合并到 ``detect._utils.adaptive_padding``；
``_to_L_image`` / 灰度转换走 ``detect._utils``。本模块不再重复。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image

from book_cut.detect._utils import adaptive_padding, to_gray_array, to_L_image

if TYPE_CHECKING:
    from book_cut.detect.paper import CropConfig


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    """ndarray (uint8) → L mode PIL Image（trim/binarize 共用）。

    v1.6+ C2：薄包装到 ``detect._utils.to_L_image``，保留本名供本模块引用。
    """
    return to_L_image(arr_u8)


def _safety_margin(h: int, w: int) -> int:
    """v1.6+ B线：贴边保护阈值（严格模式）。

    公式：``max(5, int(min(h, w) * 0.01))``。
    - 4000×4000 → 40px
    - 500×500 → 5px (floor)

    短边 < 500px 时退化到 5px（floor）。
    """
    return max(5, int(min(h, w) * 0.01))


def _safety_margin_relaxed(h: int, w: int) -> int:
    """v1.8.2+：放宽的贴边保护阈值（fallback 模式）。

    严格 safety 命中（内容贴边）→ 仍想尝试裁切时使用。
    公式：``max(2, int(min(h, w) * 0.005))`` —— 比严格模式减半。
    - 4000×4000 → 20px
    - 500×500 → 2px (floor)
    """
    return max(2, int(min(h, w) * 0.005))


def _safety_check(top: int, bottom: int, left: int, right: int, h: int, w: int, safety: int) -> bool:
    """检测内容是否在 safety 内（True = 贴边，需要 fallback 或放弃）。"""
    return (
        top < safety
        or bottom > h - safety - 1
        or left < safety
        or right > w - safety - 1
    )


def _clean_ink_mask(ink_mask: np.ndarray, use_morph: bool) -> np.ndarray:
    """v1.6+ B线：形态学开运算抗尘点（1-3 px 孤立点）。

    3×3 开运算效果：
    - 1 像素孤立点 → 清除
    - 2 像素短线段 → 清除
    - 3×3 实心块 → 保留
    - 文字笔画（≥ 4 像素宽）→ 保留

    v1.8.2+：稀疏墨迹保护。
    实测发现：5% 密度随机噪点（扫描 PDF 常见情况）走 MORPH_OPEN 后**全部消失**，
    因为 3×3 erode 会清除所有孤立像素，导致 trim 以为"无内容"→ 不裁。
    修复：先用连通域分析判断是否真有"小噪点"，有则清掉；否则跳过。

    Args:
        ink_mask: 灰度图转出的二值 mask（bool 或 uint8）。
        use_morph: True 走 MORPH_OPEN；False 跳过（古籍飞白/极小字可见）。

    Returns:
        清理后的 mask（bool，与输入 dtype 无关）。
    """
    if not use_morph:
        return ink_mask.astype(bool)
    mask_u8 = ink_mask.astype(np.uint8)
    h, w = mask_u8.shape
    total_ink = int(mask_u8.sum())
    if total_ink == 0:
        return mask_u8.astype(bool)
    # v1.8.2+：若墨迹密度 < 0.5%，跳过 morph（否则会把稀疏笔画清光）
    density = total_ink / (h * w)
    if density < 0.005:
        return mask_u8.astype(bool)
    cleaned = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cleaned.astype(bool)


def _trim_margins_from_array(
    arr: np.ndarray,
    *,
    config: CropConfig | None = None,
    threshold: int | None = None,
    padding: int | None = None,
    use_morph: bool = True,
) -> Image.Image:
    """trim 核心逻辑（v1.5+ A1：接受 ndarray，返回 Image）。

    公共函数 ``trim_margins`` 的薄包装去掉后，逻辑全在这里。
    pipeline 在主循环一次 ``convert("L")`` 后直接调本函数，跳过重复转换。

    v1.6+ 改动：
    - 加 ``use_morph`` 参数控制形态学开运算（默认 True）
    - 加 safety margin 检查：内容贴图边 → 不裁
    - 统一 ``min_ink ≥ 3``（legacy 1→3，杀 JPEG 噪声）
    """
    h, w = arr.shape

    # 选择模式：config 优先；否则用 legacy 显式参数；再否则默认 240/10
    if config is not None:
        ink_thr = config.ink_threshold
        # v1.6+ C2：padding 兜底公式统一到 ``detect._utils.adaptive_padding``
        pad = config.padding if config.padding is not None else adaptive_padding(h, w)
        # v1.6+：min_ink 统一 ≥ 3（adaptive 默认即 3，防御性 max 保留）
        min_ink = max(3, config.min_edge_ink)
    else:
        ink_thr = threshold if threshold is not None else 240
        pad = padding if padding is not None else 10
        # v1.6+：legacy 与 adaptive 对齐，min_ink ≥ 3（杀 JPEG 噪声 / 单像素尘点）
        min_ink = 3

    ink_mask = arr < ink_thr
    ink_mask = _clean_ink_mask(ink_mask, use_morph=use_morph)

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

    # v1.6+ B线 → v1.8.2+：safety margin 二级 fallback。
    # 1) 严格 safety 命中（内容贴边）→ 放宽到 relaxed safety 重试
    # 2) relaxed safety 仍命中 → 放弃整页（保守策略：宁可漏裁不伤字）
    safety_strict = _safety_margin(h, w)
    if _safety_check(top, bottom, left, right, h, w, safety_strict):
        safety_relaxed = _safety_margin_relaxed(h, w)
        if _safety_check(top, bottom, left, right, h, w, safety_relaxed):
            return _to_L_image(arr)

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
    use_morph: bool = True,
) -> Image.Image:
    """去掉图片四周的白边。

    策略：扫描每行/列，把"有内容"行/列的首末位置作为裁切边界，外加 padding。

    v1.5+ A1：薄包装，convert("L") 后调 ``_trim_margins_from_array``。
    v1.6+ 加 ``use_morph`` 参数（默认 True），CLI ``--no-morph`` 关闭形态学。

    Args:
        image: 输入图像。
        threshold: 灰度值 < threshold 视为有内容（legacy）。
            缺省 = 240。``config`` 不为 None 时忽略。
        padding: 保留的最小边距（像素，legacy）。缺省 = 10。
            ``config`` 不为 None 时忽略（用 config.padding / 自适应）。
        config: 自适应裁切配置。``None`` = legacy 模式。
        use_morph: 是否走形态学开运算（v1.6+ B线，默认 True）。
            关闭后保留 1-3 px 飞白/极小字，但失去抗尘点能力。

    Returns:
        裁切后的图像。
    """
    # v1.6+ C2：灰度转换走 ``detect._utils.to_gray_array``（行为等价）
    arr = to_gray_array(image)
    return _trim_margins_from_array(
        arr, config=config, threshold=threshold, padding=padding, use_morph=use_morph
    )
