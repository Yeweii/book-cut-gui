"""版框内裁：检测单页的外框线（版框），裁切到版框内部。

Canny/Hough 参数保持静态（几何检测，不受 paper color 影响）。
当版框检测失败时回退到 ``trim_margins``，trim 现在会接收 adaptive config
（来自 ``book_cut.detect.paper``）。

v1.5+ A1：``crop_to_border_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
v1.6+ A线：默认 ``padding`` 由 5 翻倍到 10，保护贴版框字符（4-5px 笔画）。
v1.9.2 A：外框候选过滤 —— 候选 x/y 位置必须在该位置上有连续 ≥ ``min_outer_span`` 的
dark run（竖线 ≥ ``min_v_span`` ≈ 0.4 h，横线 ≥ ``min_h_span`` ≈ 0.4 w）。
古籍扫描常常**只有内栏线、没有完整外框**，Hough 容易把栏线当成外框误裁。
要求"贯穿"过滤掉栏线候选；若过滤后 < 2 竖 / < 2 横 → fallback trim。
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

    # v1.9.2 A：外框候选过滤 —— Hough 检测到的 vs/hs 包含栏线 / 注释横线等"短候选"，
    # 真正的外框必须**贯穿**相当比例的图。检查每个候选 x/y 位置的最长连续 dark run：
    # - 竖线候选 x：该列最长连续 dark run ≥ 0.4 * h 才算外框
    # - 横线候选 y：该行最长连续 dark run ≥ 0.4 * w 才算外框
    # 古籍扫描常常"有栏线无外框"，不这样过滤会把栏线当成外框误裁内容。
    # v1.9.2 A fix：Hough 代表坐标（簇中位数）可能比真实墨迹列偏 1-2 px
    # （PIL outline=2 在目标 x 两侧各画 1px，但 Hough 检测的"线"取的是
    # 边缘梯度的中点）。检查 ±1 邻域的最长 run，避免误杀。
    min_v_span = int(0.4 * h)
    min_h_span = int(0.4 * w)

    def _longest_dark_run(strip: np.ndarray, dark_thr: int = 240) -> int:
        """strip 上最长连续 dark 像素长度。"""
        if strip.size == 0:
            return 0
        is_dark = strip < dark_thr
        if not is_dark.any():
            return 0
        # 找最长 True 连续段
        changes = np.diff(is_dark.astype(np.int8))
        starts = np.where(changes == 1)[0] + 1
        ends = np.where(changes == -1)[0] + 1
        if is_dark[0]:
            starts = np.concatenate(([0], starts))
        if is_dark[-1]:
            ends = np.concatenate((ends, [len(is_dark)]))
        return int((ends - starts).max())

    def _col_run(x: int) -> int:
        """x 附近 ±1 列的最长连续 dark run（Hough 坐标可能有 ±1-2 偏移）。

        取窗口内每列的 run，取最大值（不能 flatten，否则跨列的 dark 会被错位断开）。
        """
        lo, hi = max(0, x - 1), min(w, x + 2)
        if lo >= hi:
            return 0
        return max(_longest_dark_run(arr[:, cx]) for cx in range(lo, hi))

    def _row_run(y: int) -> int:
        lo, hi = max(0, y - 1), min(h, y + 2)
        if lo >= hi:
            return 0
        return max(_longest_dark_run(arr[cy, :]) for cy in range(lo, hi))

    vs_outer = [x for x in vs if _col_run(x) >= min_v_span]
    hs_outer = [y for y in hs if _row_run(y) >= min_h_span]

    if len(vs_outer) < 2 or len(hs_outer) < 2:
        # 外框候选不足 → 当作"无外框"，退到 trim（让 trim 切白边）
        from book_cut.detect.trim import _trim_margins_from_array

        return _trim_margins_from_array(arr, padding=padding, config=config, use_morph=use_morph)

    left = vs_outer[0]
    right = vs_outer[-1]
    top = hs_outer[0]
    bottom = hs_outer[-1]

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
