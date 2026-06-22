"""版框内裁：检测单页的外框线（版框），裁切到版框内部。

Canny/Hough 参数保持静态（几何检测，不受 paper color 影响）。
当版框检测失败时回退到 ``trim_margins``，trim 现在会接收 adaptive config
（来自 ``book_cut.detect.paper``）。

v1.5+ A1：``crop_to_border_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
v1.6+ A线：默认 ``padding`` 由 5 翻倍到 10，保护贴版框字符（4-5px 笔画）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from book_cut.detect.paper import CropConfig


def _to_gray(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.uint8)


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    return Image.fromarray(arr_u8, mode="L")


def _detect_lines(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
    """返回 (竖线 x 列表, 横线 y 列表)。

    v1.5+ C1：调共享 ``detect_lines`` + ``cluster_lines``，参数与 v1.4 等价
    （threshold=60, min_length_factor=30, max_gap=8）。
    """
    from book_cut.detect._hough import HOUGH_PRESET_CROP_BORDER, cluster_lines, detect_lines

    lines = detect_lines(gray, **HOUGH_PRESET_CROP_BORDER)
    if lines is None:
        return None

    vs, hs = cluster_lines(lines)
    if not vs or not hs:
        return None
    return vs, hs


def crop_to_border_from_array(
    arr: np.ndarray,
    padding: int = 10,
    config: CropConfig | None = None,
    use_morph: bool = True,
    page_rect: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """版框内裁核心（v1.5+ A1：接受 ndarray，返回 Image）。

    v1.6+：默认 ``padding=10``（v1.5 之前 5；翻倍保护贴版框字符）。
    v1.6+：加 ``use_morph`` 参数透传给 trim fallback。
    v1.6+ A3：加 ``page_rect`` 参数 —— 若提供（``split_border_with_rects_from_array``
            已经检测到版框），直接用 rect 裁切，**跳过 Hough + Canny + cluster**（省 ~4ms/页）。

    找不到版框时回退到 ``_trim_margins_from_array``（trim 的 from_array 变体），
    行为与 ``crop_to_border`` 完全一致。
    """
    h, w = arr.shape

    # v1.6+ A3：缓存的 page_rect 优先 —— 跳过 Hough
    if page_rect is not None:
        rect_left, rect_top, rect_right, rect_bottom = page_rect
        # sanity check：rect 应在图像范围内且非退化
        if (
            rect_left < rect_right
            and rect_top < rect_bottom
            and rect_right > 0
            and rect_bottom > 0
            and rect_left < w
            and rect_top < h
        ):
            cl = max(0, rect_left + padding)
            ct = max(0, rect_top + padding)
            cr = min(w, rect_right - padding)
            cb = min(h, rect_bottom - padding)
            if cr > cl and cb > ct:
                return _to_L_image(arr[ct:cb, cl:cr])
            # rect 退化（加 padding 后无效）→ 退到原 Hough 路径

    result = _detect_lines(arr)
    if result is None:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config, use_morph=use_morph)

    vs, hs = result
    if len(vs) < 2 or len(hs) < 2:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config, use_morph=use_morph)

    left = vs[0]
    right = vs[-1]
    top = hs[0]
    bottom = hs[-1]

    # 合理性检查：版框应包含图像主体
    if (right - left) < w * 0.2 or (bottom - top) < h * 0.2:
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config, use_morph=use_morph)

    # 裁到版框内部（含 padding）
    cl = max(0, left + padding)
    ct = max(0, top + padding)
    cr = min(w, right - padding)
    cb = min(h, bottom - padding)

    if cr <= cl or cb <= ct:
        return _to_L_image(arr)

    return _to_L_image(arr[ct:cb, cl:cr])


def crop_to_border(
    image: Image.Image,
    padding: int = 10,
    config: CropConfig | None = None,
    use_morph: bool = True,
    page_rect: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    """检测版框并裁切到版框内部。

    找不到版框时回退到 ``trim_margins``，并把 ``config`` 传过去（v1.3+）。

    v1.5+ A1：薄包装，调 ``crop_to_border_from_array``。
    v1.6+ 默认 ``padding=10``（v1.5 之前 5）。
    v1.6+ 加 ``use_morph`` 参数透传给 trim fallback。
    v1.6+ A3 加 ``page_rect`` 参数（split_border 缓存的版框 rect）。

    Args:
        image: 单页图像（已经切分后）。
        padding: 距版框的内边距（像素）。
        config: 自适应裁切配置。``None`` = legacy 模式（传给 trim 时也是 legacy）。
            传给 trim 时 ``padding`` 仍可独立指定。
        use_morph: trim fallback 是否走形态学开运算（v1.6+ B线）。
        page_rect: v1.6+ A3 split_border 缓存的版框 rect（子图坐标）。
    """
    arr = _to_gray(image)
    return crop_to_border_from_array(
        arr, padding=padding, config=config, use_morph=use_morph, page_rect=page_rect
    )
