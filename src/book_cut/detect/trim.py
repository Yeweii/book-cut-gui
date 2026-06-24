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


def _longest_dark_run(strip: np.ndarray, dark_thr: int = 240) -> int:
    """v1.9.2 B：strip 上最长连续 dark 像素长度。

    用于区分"真实内容"（长 run，≥ 100px）和"扫描噪点/边缘杂点"（短 run，< 100px）。
    """
    if strip.size == 0:
        return 0
    is_dark = strip < dark_thr
    if not is_dark.any():
        return 0
    padded = np.concatenate(([False], is_dark, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]
    return int((ends - starts).max())


def _longest_dark_run_per_row(arr: np.ndarray, dark_thr: int = 240) -> np.ndarray:
    """v1.9.2 B：每行最长连续 dark run 长度（shape ``(h,)``）。"""
    is_dark = arr < dark_thr  # (h, w)
    h, w = is_dark.shape
    # Pad 行首尾
    padded = np.concatenate([np.zeros((h, 1), dtype=bool), is_dark, np.zeros((h, 1), dtype=bool)], axis=1)
    diff = np.diff(padded.astype(np.int8), axis=1)  # (h, w+1)
    starts = diff == 1
    ends = diff == -1
    # run lengths at end positions
    out = np.zeros(h, dtype=np.int32)
    for i in range(h):
        s = np.where(starts[i])[0]
        e = np.where(ends[i])[0]
        if len(s) > 0:
            out[i] = int((e - s).max())
    return out


def _longest_dark_run_per_col(arr: np.ndarray, dark_thr: int = 240) -> np.ndarray:
    """v1.9.2 B：每列最长连续 dark run 长度（shape ``(w,)``）。"""
    return _longest_dark_run_per_row(arr.T, dark_thr=dark_thr)


def _safety_check(top: int, bottom: int, left: int, right: int, h: int, w: int, safety: int) -> bool:
    """检测内容是否在 safety 内（True = 贴边，需要 fallback 或放弃）。"""
    return (
        top < safety
        or bottom > h - safety - 1
        or left < safety
        or right > w - safety - 1
    )


def _safety_check_noise_aware(
    top: int,
    bottom: int,
    left: int,
    right: int,
    h: int,
    w: int,
    safety: int,
    row_longest: np.ndarray,
    col_longest: np.ndarray,
    noise_thr: int = 100,
) -> bool:
    """v1.9.2 B：safety 检查的噪点豁免版。

    与 ``_safety_check`` 行为一致，但若贴边的 col/row 是"零散噪点"
    （longest_run < ``noise_thr``），该边不算命中。
    古籍扫描边缘噪点 longest run 通常 30-70 px，远小于 border frame (1000+)、
    文字栏线 (300+) 和稀疏 1px 测试点 (1)，但仍然触发旧 safety。

    Args:
        row_longest / col_longest: 来自 ``_longest_dark_run_per_row/col``。
        noise_thr: longest_run 低于此值视为噪点（默认 100）。
    """
    NOISE_THR = noise_thr

    def _is_real_edge_collision(
        pos: int, axis_size: int, longest_at_pos: int, is_low_side: bool
    ) -> bool:
        """pos 是否真的"贴边 + 是真实内容"（非噪点）。"""
        if is_low_side:
            if pos >= safety:
                return False  # 不贴边
        else:
            if pos <= axis_size - safety - 1:
                return False  # 不贴边
        # 贴边 → 看是不是噪点
        return longest_at_pos >= NOISE_THR

    return (
        _is_real_edge_collision(top, h, int(row_longest[top]), True)
        or _is_real_edge_collision(bottom, h, int(row_longest[bottom]), False)
        or _is_real_edge_collision(left, w, int(col_longest[left]), True)
        or _is_real_edge_collision(right, w, int(col_longest[right]), False)
    )


# v2.1+ E2：trim 版框检测参数默认值（trim_frame 方案）
_DEFAULT_FRAME_MIN_BBOX_RATIO = 0.30  # bbox ≥ 30% 图像面积
_DEFAULT_FRAME_MAX_FILL_RATIO = 0.15  # 填充率 ≤ 15%（空心=边框）
_DEFAULT_FRAME_ASPECT_RANGE = (0.5, 1.0)  # 页形 w/h
_DEFAULT_FRAME_EDGE_MARGIN = 5  # bbox 距图边 ≥ 5px
_DEFAULT_FRAME_MORPH_KERNEL = 5  # 修补版框线断裂的 CLOSE 核


def detect_frame_bbox(
    ink_mask: np.ndarray,
    *,
    min_bbox_ratio: float = _DEFAULT_FRAME_MIN_BBOX_RATIO,
    max_fill_ratio: float = _DEFAULT_FRAME_MAX_FILL_RATIO,
    aspect_range: tuple[float, float] = _DEFAULT_FRAME_ASPECT_RANGE,
    edge_margin: int = _DEFAULT_FRAME_EDGE_MARGIN,
    morph_kernel: int = _DEFAULT_FRAME_MORPH_KERNEL,
) -> tuple[int, int, int, int] | None:
    """检测最大的"空心矩形"连通区 bbox（即古籍版框/页面外边框）。

    v2.1+ E2（trim_frame 方案，``docs/dev/2026-06-24-v2.1-trim-frame.md``）：
    用作 trim 的"严格裁切边界"，替代"第一个含墨迹像素"的宽松策略。
    解决古籍扫描中"版框外零散噪点/印章/页码"导致 trim 留过多白边的问题。

    算法：
        1. 形态学 CLOSE 修补版框线断裂（默认 5×5 核）
        2. ``cv2.connectedComponentsWithStats`` 拿所有连通区
        3. 筛候选（同时满足）：
            - bbox_area / image_area ≥ ``min_bbox_ratio``（大面积）
            - filled_pixels / bbox_area ≤ ``max_fill_ratio``（空心=边框）
            - bbox aspect (w/h) ∈ ``aspect_range``（页形）
            - bbox 不贴图边 ≥ ``edge_margin`` px（版框外有白边）
        4. 取 bbox_area 最大的候选 → 版框 bbox

    Args:
        ink_mask: 二值 ink mask（bool 或 uint8，True=墨迹）。
        min_bbox_ratio: bbox 面积占图像面积的最小比例（默认 0.30）。
            太小（如页眉小框）会被滤掉。
        max_fill_ratio: bbox 内墨迹占 bbox 面积的最大比例（默认 0.15）。
            实心块（fill=100%）会被滤掉，只留空心框。
        aspect_range: bbox 的 (w/h) 范围（默认 (0.5, 1.0)，适合竖版单页）。
            双页扫描（横版）需调成 (1.0, 2.0)。
        edge_margin: bbox 距图像边缘最小距离（默认 5 px）。
            版框外必有白边，否则认为是扫描边线而非版框。
        morph_kernel: 修补版框线断裂的 CLOSE 核大小（默认 5）。
            太大可能合并多个版框；太小修补不了断裂。

    Returns:
        ``(top, bottom, left, right)``：版框 bbox（含），或 ``None``
        （无候选 → 调用方走 fallback）。
    """
    if ink_mask is None or not ink_mask.any():
        return None
    mask_u8 = ink_mask.astype(np.uint8)
    H, W = mask_u8.shape
    total = H * W

    # 步骤 1：形态学闭运算修补版框线断裂
    if morph_kernel > 1:
        kernel = np.ones((morph_kernel, morph_kernel), np.uint8)
        closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    else:
        closed = mask_u8

    # 步骤 2：连通域
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    if n_labels <= 1:
        return None

    # 步骤 3：筛候选
    candidates: list[tuple[int, tuple[int, int, int, int]]] = []
    aspect_lo, aspect_hi = aspect_range
    for i in range(1, n_labels):
        x, y, w, h, area = stats[i]
        bbox_area = int(w) * int(h)
        if bbox_area <= 0:
            continue
        # 大面积过滤
        if bbox_area / total < min_bbox_ratio:
            continue
        # 空心过滤（实心块 = 非版框）
        if area / bbox_area > max_fill_ratio:
            continue
        # 页形过滤
        aspect = w / h
        if not (aspect_lo <= aspect <= aspect_hi):
            continue
        # 不贴边过滤（版框外有白边）
        if x < edge_margin or y < edge_margin:
            continue
        if x + w > W - edge_margin:
            continue
        if y + h > H - edge_margin:
            continue
        top = int(y)
        bottom = int(y + h - 1)
        left = int(x)
        right = int(x + w - 1)
        candidates.append((bbox_area, (top, bottom, left, right)))

    if not candidates:
        return None
    # 步骤 4：取 bbox 最大的（版框总比鱼尾/版心装饰大）
    return max(candidates, key=lambda c: c[0])[1]


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


# v2.1+：CCA 主体过滤（trim B 方案）
_ASPECT_THRESHOLD = 10.0  # aspect ratio > 此值视为狭长（版框线/注释横线）


def _filter_main_components(
    ink_mask: np.ndarray,
    min_area: float,
    gutter_band: tuple[float, float] | None = None,
    gutter_bands: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """滤掉小连通区 + 狭长版框线，返回主体 mask。

    v2.1+ B 方案（``docs/dev/2026-06-24-v2.1-trim-ab.md`` §4）。
    v2.1+ D 方案（``docs/dev/2026-06-24-v2.1-trim-yuwei-preserve.md``）：可选
    ``gutter_band`` 版心保护区 —— bbox 中心落在该列带的连通区豁免（保留鱼尾等
    版心装饰）。
    v2.1+ G 方案：``gutter_bands: list[tuple]`` 支持多个保护带（双页扫描右侧
    副页保留）。连通区 bbox 中心列落在**任一** band 内即豁免 aspect 过滤。

    滤除条件（任一满足即滤）：
    1. area < ``min_area``（小噪点）
    2. aspect ratio (max(h,w) / min(h,w)) > ``_ASPECT_THRESHOLD``（狭长版框线）

    版心豁免：
    - ``gutter_band`` (单 band, 向后兼容) 或 ``gutter_bands`` (多 band, v2.1+ G)
    - 连通区 bbox 中心列落在任一带 → 跳过 aspect 过滤（保留版心装饰）
    - 仍受 min_area 阈值约束（小噪点仍滤）

    边界处理：
    - min_area <= 0 → 原样返回（关闭 CCA 过滤）
    - mask 全空 → 原样返回
    - 过滤后无任何保留 → fallback 原 mask（避免 bbox 退化到全图）

    Args:
        ink_mask: 灰度图转出的二值 mask（bool）。
        min_area: 保留连通区的最小面积阈值。
        gutter_band: 版心保护带 (left_frac, right_frac)，None=关闭（向后兼容旧 API）。
        gutter_bands: 版心保护带列表 [(L1, R1), (L2, R2), ...]，None=关闭（v2.1+ G）。
            任一非空即合并到统一 band 列表中（``gutter_band`` 也算单元素）。

    Returns:
        过滤后的 mask（bool）。
    """
    if min_area <= 0:
        return ink_mask
    if not ink_mask.any():
        return ink_mask
    mask_u8 = ink_mask.astype(np.uint8)
    h_total, w_total = mask_u8.shape
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if n_labels <= 1:
        return ink_mask
    # v2.1+ G：合并单 band + 多 band 为统一 list
    bands: list[tuple[float, float]] = []
    if gutter_band is not None:
        bands.append(gutter_band)
    if gutter_bands:
        bands.extend(gutter_bands)
    keep = np.zeros_like(ink_mask, dtype=bool)
    kept_any = False
    # v2.1+ D：版心保护 —— 在版心带内的连通区使用更宽松的阈值
    # （鱼尾/版心装饰条 area 普遍 < 100，但形态学上不是噪点）。
    # 兜底：min_area_floor=4，只滤 1-3 px 单像素尘点。
    GUTTER_MIN_AREA_FLOOR = 4
    for i in range(1, n_labels):
        x, y, w, h, area = stats[i]
        # v2.1+ G：判断是否在任一 band 内（bbox 中心列）
        in_gutter = False
        if bands:
            cx = x + w / 2.0
            for left_frac, right_frac in bands:
                if (left_frac * w_total) <= cx < (right_frac * w_total):
                    in_gutter = True
                    break
        # v2.1+ D：版心内用更小的面积阈值（保留鱼尾小碎片）
        effective_min_area = GUTTER_MIN_AREA_FLOOR if in_gutter else min_area
        if area < effective_min_area:
            continue
        aspect = max(h, w) / max(min(h, w), 1)
        # v2.1+ D：版心豁免 —— 在版心带内的狭长连通区不滤（保留版心装饰条）
        if aspect > _ASPECT_THRESHOLD and not in_gutter:
            continue
        keep |= labels == i
        kept_any = True
    # fallback：所有连通区都被滤 → 保留原 mask
    return keep if kept_any else ink_mask


def _trim_margins_from_array(
    arr: np.ndarray,
    *,
    config: CropConfig | None = None,
    threshold: int | None = None,
    padding: int | None = None,
    use_morph: bool = True,
    trim_source: str = "gray",
    min_component_ratio: float = 0.0,
    extra_padding: int = 0,
    gutter_band: tuple[float, float] | None = None,
    gutter_bands: list[tuple[float, float]] | None = None,
    horizontal: bool = True,
    strict: bool = False,
    trim_frame: bool = False,
    trim_frame_min_ratio: float = _DEFAULT_FRAME_MIN_BBOX_RATIO,
    trim_frame_max_fill: float = _DEFAULT_FRAME_MAX_FILL_RATIO,
    trim_frame_aspect: tuple[float, float] = _DEFAULT_FRAME_ASPECT_RANGE,
) -> Image.Image:
    """trim 核心逻辑（v1.5+ A1：接受 ndarray，返回 Image）。

    公共函数 ``trim_margins`` 的薄包装去掉后，逻辑全在这里。
    pipeline 在主循环一次 ``convert("L")`` 后直接调本函数，跳过重复转换。

    v1.6+ 改动：
    - 加 ``use_morph`` 参数控制形态学开运算（默认 True）
    - 加 safety margin 检查：内容贴图边 → 不裁
    - 统一 ``min_ink ≥ 3``（legacy 1→3，杀 JPEG 噪声）
    - CLI opt-out：``--no-morph`` 关闭形态学（古籍飞白/极小字可见时用）

    v2.1+ 改动：
    - 加 ``strict`` 参数（v2.1+ B 方案）：True 时后置过滤稀疏行（排除页眉/页脚）。
      算法：row ink 阈值 = max(50, max_row_ink × 0.1)，低于阈值的行不进 bbox。
      与 A+B（C 选项 ``extra_padding``）互补：A+B 控制 column 过滤（aspect），
      strict 控制 row 过滤（密度）。

    v2.1+ 改动（trim A+B 实验，``docs/dev/2026-06-24-v2.1-trim-ab.md``）：
    - 加 ``trim_source`` 参数："gray"（默认，行为不变）/"binarized"（走 binarize 拿 ink mask）
    - 加 ``min_component_ratio`` 参数：>0 时启用 CCA 主体过滤（同时滤小连通区 + 狭长版框线）
    - 加 ``extra_padding`` 参数：在 adaptive/legacy padding 之上**叠加** N 像素（默认 0）。
      解决 A+B 启用后版框/版心标记紧贴输出边缘的问题。

    Args:
        arr: 灰度 ndarray (uint8, shape=(h,w))
        config: 自适应裁切配置。None=legacy。
        threshold: legacy 灰度阈值。None=240。config 优先。
        padding: legacy padding。None=10。config 优先。
        use_morph: 是否走形态学开运算清 1-3px 噪点。
        trim_source: "gray"（默认）/ "binarized"（走 binarize 拿 mask，v2.1+ A 方案）
        min_component_ratio: CCA 主体过滤阈值。0=关闭；>0=启用
            （area < ratio*total OR aspect>10 → 滤掉）。v2.1+ B 方案。
        extra_padding: v2.1+ C。在 adaptive/legacy padding 之上**叠加** N 像素。
            默认 0，行为不变。>0 时给版框/版心标记留视觉呼吸空间。
        gutter_band: v2.1+ D。版心保护区 (left_frac, right_frac)。
            None=关闭（默认）。设值后，连通区 bbox 中心列落在该列带的连通区
            豁免 CCA aspect 过滤（保留版心鱼尾等装饰），但仍受 min_area 约束。
            需配合 ``min_component_ratio > 0`` 生效。
        gutter_bands: v2.1+ G。版心保护区列表 ``[(L1, R1), (L2, R2), ...]``。
            None=关闭（默认）。连通区 bbox 中心列落在**任一**带内即豁免。
            适用于双页扫描右侧副页保留场景（同时保留中央版心 + 右侧副页区）。
            需配合 ``min_component_ratio > 0`` 生效。与 ``gutter_band`` 共存时合并。
        horizontal: v2.1+ E。是否横向裁切。
            True=默认（行为不变）：横竖都按 ink bbox 裁切。
            False=仅竖向裁切：保留输入全宽，只裁上下空白。
            用于 ``--split none`` 模式（输入已是单页/double-page 不想拆分时）。
        trim_frame: v2.1+ E2。是否启用版框检测（古籍版框页专用）。
            True → 先用 ``detect_frame_bbox`` 找最大空心矩形作为 bbox，
            失败则 fallback 到 ink bbox。False → 走原 trim 路径（向后兼容）。
        trim_frame_min_ratio: v2.1+ E2。版框 bbox 占图像面积最小比例。
            默认 0.30（详见 ``detect_frame_bbox``）。
        trim_frame_max_fill: v2.1+ E2。版框 bbox 填充率上限（空心判定）。
            默认 0.15。
        trim_frame_aspect: v2.1+ E2。版框 bbox 宽高比范围。
            默认 (0.5, 1.0)（竖版单页）。
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
    # v2.1+ C：在 adaptive/legacy 之上叠加额外 padding（opt-in，向后兼容）
    pad = pad + max(0, extra_padding)

    # v2.1+ A 方案：可选走二值化拿 ink mask（抗 paper color 估计偏差）
    if trim_source == "binarized":
        try:
            from book_cut.preprocess.binarize import binarize

            # 用 otsu（快 + 通用），binarize 内部走 sauvola 时更准但慢
            # binary_mode="8bit" 拿 uint8 输出方便 < 128 比较
            bin_img = binarize(arr, method="otsu", binary_mode="8bit")
            bin_arr = np.asarray(bin_img.convert("L"))
            ink_mask = bin_arr < 128
        except Exception:
            # binarize 失败 → fallback 到 gray 路径（保底）
            ink_mask = arr < ink_thr
    else:
        ink_mask = arr < ink_thr

    ink_mask = _clean_ink_mask(ink_mask, use_morph=use_morph)

    # v2.1+ B 方案：CCA 主体过滤（同时滤小连通区 + 狭长版框线）
    # v2.1+ D：gutter_band 启用后，版心带内连通区豁免 aspect 过滤（保留鱼尾）
    # v2.1+ G：gutter_bands 列表支持多个保护带（双页扫描右侧副页保留）
    if min_component_ratio > 0:
        ink_mask = _filter_main_components(
            ink_mask,
            min_component_ratio * ink_mask.size,
            gutter_band=gutter_band,
            gutter_bands=gutter_bands,
        )

    # v2.1+ E2：版框检测 —— 优先用最大空心矩形 bbox
    # 成功 → 用版框 bbox 替代下面 ink bbox 计算
    # 失败 → fallback 到 ink bbox（与原 trim 行为一致）
    frame_bbox = None
    if trim_frame:
        frame_bbox = detect_frame_bbox(
            ink_mask,
            min_bbox_ratio=trim_frame_min_ratio,
            max_fill_ratio=trim_frame_max_fill,
            aspect_range=trim_frame_aspect,
        )

    if frame_bbox is not None:
        top, bottom, left, right = frame_bbox
        # 版框命中：跳过 ink bbox 计算（直接走 safety + padding）
        col_longest = _longest_dark_run_per_col(arr, dark_thr=ink_thr)
        row_longest = _longest_dark_run_per_row(arr, dark_thr=ink_thr)

        safety_strict = _safety_margin(h, w)
        if _safety_check_noise_aware(
            top, bottom, left, right, h, w, safety_strict, row_longest, col_longest
        ):
            safety_relaxed = _safety_margin_relaxed(h, w)
            if _safety_check_noise_aware(
                top, bottom, left, right, h, w, safety_relaxed, row_longest, col_longest
            ):
                return _to_L_image(arr)

        # 应用 padding（不超出原图）
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = min(h - 1, bottom + pad)
        right = min(w - 1, right + pad)

        if bottom <= top or right <= left:
            return _to_L_image(arr)

        return _to_L_image(arr[top : bottom + 1, left : right + 1])

    # 常规路径：ink bbox
    row_has_content = ink_mask.sum(axis=1) >= min_ink
    col_has_content = ink_mask.sum(axis=0) >= min_ink

    # v2.1+ B 方案：strict 后置过滤 —— 排除稀疏行（页眉/页脚/边缘噪点）
    # 阈值：max(50, max_row_ink × 0.1)，自适应 + 50 兜底
    if strict:
        row_ink = ink_mask.sum(axis=1)
        max_row_ink = int(row_ink.max()) if len(row_ink) > 0 else 0
        strict_threshold = max(50, int(max_row_ink * 0.1))
        row_has_content = row_ink >= strict_threshold

    rows_idx = np.where(row_has_content)[0]
    cols_idx = np.where(col_has_content)[0]

    if len(rows_idx) == 0 or len(cols_idx) == 0:
        # 全白/全非白：原图返回（重建 Image）
        return _to_L_image(arr)

    top = int(rows_idx[0])
    bottom = int(rows_idx[-1])
    # v2.1+ E：horizontal=False 时保留输入全宽（不裁左右）
    if horizontal:
        left = int(cols_idx[0])
        right = int(cols_idx[-1])
    else:
        left = 0
        right = w - 1

    # v1.9.2 B：safety 检查的"噪点豁免"。
    # 旧逻辑只看 col/row 位置：贴边 → safety 命中 → 不裁。
    # 现实古籍扫描边缘常有几十像素的零散噪点（最左/最右列 longest run 仅 50-70 px），
    # 触发 safety 但其实是噪点，应允许裁掉外侧白边。
    # 修复：如果贴边的 col/row 是"零散噪点"（longest_run < NOISE_THR），
    # 则该边不算 safety 命中。
    col_longest = _longest_dark_run_per_col(arr, dark_thr=ink_thr)
    row_longest = _longest_dark_run_per_row(arr, dark_thr=ink_thr)

    safety_strict = _safety_margin(h, w)
    if _safety_check_noise_aware(
        top, bottom, left, right, h, w, safety_strict, row_longest, col_longest
    ):
        safety_relaxed = _safety_margin_relaxed(h, w)
        if _safety_check_noise_aware(
            top, bottom, left, right, h, w, safety_relaxed, row_longest, col_longest
        ):
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
    trim_source: str = "gray",
    min_component_ratio: float = 0.0,
    extra_padding: int = 0,
    gutter_band: tuple[float, float] | None = None,
    gutter_bands: list[tuple[float, float]] | None = None,
    horizontal: bool = True,
    strict: bool = False,
    trim_frame: bool = False,
    trim_frame_min_ratio: float = _DEFAULT_FRAME_MIN_BBOX_RATIO,
    trim_frame_max_fill: float = _DEFAULT_FRAME_MAX_FILL_RATIO,
    trim_frame_aspect: tuple[float, float] = _DEFAULT_FRAME_ASPECT_RANGE,
) -> Image.Image:
    """去掉图片四周的白边。

    策略：扫描每行/列，把"有内容"行/列的首末位置作为裁切边界，外加 padding。

    v1.5+ A1：薄包装，convert("L") 后调 ``_trim_margins_from_array``。
    v1.6+ 加 ``use_morph`` 参数（默认 True），CLI ``--no-morph`` 关闭形态学。
    v2.1+ 加 ``trim_source`` / ``min_component_ratio`` 参数（trim A+B 实验）。
    v2.1+ 加 ``extra_padding`` 参数（trim C：在 adaptive 之上叠加 N 像素）。

    Args:
        image: 输入图像。
        threshold: 灰度值 < threshold 视为有内容（legacy）。
            缺省 = 240。``config`` 不为 None 时忽略。
        padding: 保留的最小边距（像素，legacy）。缺省 = 10。
            ``config`` 不为 None 时忽略（用 config.padding / 自适应）。
        config: 自适应裁切配置。``None`` = legacy 模式。
        use_morph: 是否走形态学开运算（v1.6+ B线，默认 True）。
            关闭后保留 1-3 px 飞白/极小字，但失去抗尘点能力。
        trim_source: v2.1+ A 方案。"gray"（默认）/ "binarized"。
        min_component_ratio: v2.1+ B 方案。0=关闭；>0=启用 CCA 主体过滤。
        extra_padding: v2.1+ C。在 adaptive/legacy padding 之上叠加 N 像素（默认 0）。
        gutter_band: v2.1+ D。版心保护区 (left_frac, right_frac)，None=关闭。
        gutter_bands: v2.1+ G。版心保护区列表 [(L1, R1), (L2, R2), ...]，None=关闭。
            连通区 bbox 中心列落在任一带内即豁免 aspect 过滤。
        horizontal: v2.1+ E。是否横向裁切（默认 True）。
            False=保留输入全宽，只裁上下空白（``--split none`` 模式）。

    Returns:
        裁切后的图像。
    """
    # v1.6+ C2：灰度转换走 ``detect._utils.to_gray_array``（行为等价）
    arr = to_gray_array(image)
    return _trim_margins_from_array(
        arr,
        config=config,
        threshold=threshold,
        padding=padding,
        use_morph=use_morph,
        trim_source=trim_source,
        min_component_ratio=min_component_ratio,
        extra_padding=extra_padding,
        gutter_band=gutter_band,
        gutter_bands=gutter_bands,
        horizontal=horizontal,
        strict=strict,
        trim_frame=trim_frame,
        trim_frame_min_ratio=trim_frame_min_ratio,
        trim_frame_max_fill=trim_frame_max_fill,
        trim_frame_aspect=trim_frame_aspect,
    )
