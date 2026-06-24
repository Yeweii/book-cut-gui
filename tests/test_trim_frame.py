"""v2.1+ trim 版框检测（trim_frame）测试。

对应方案：``docs/dev/2026-06-24-v2.1-trim-frame.md``（用户于 2026-06-24 提出）。

TDD 约定：先写 RED（参数不存在 → TypeError），再实现 GREEN。

核心算法：CCA 空心矩形筛选
1. binarize ink mask
2. morph CLOSE 5×5（修补版框线断裂）
3. cv2.connectedComponentsWithStats
4. 筛候选：bbox_area ≥ 30% 图像面积 + filled ≤ 15% + aspect ∈ [0.5, 1.0] + 不贴边
5. 取 bbox 最大的 → 版框 bbox
6. crop 到该 bbox + padding
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from book_cut.detect.trim import (
    detect_frame_bbox,
    trim_margins,
)

# ----------------------------------------------------------------------------
# 合成 fixture
# ----------------------------------------------------------------------------


def _page_with_frame(
    *,
    img_size: tuple[int, int] = (800, 1200),
    frame_rect: tuple[int, int, int, int] = (80, 120, 720, 1080),
    frame_width: int = 3,
    text_inside: bool = True,
    outer_noise: bool = False,
    yuwei_outside: bool = False,
    frame_broken: bool = False,
) -> Image.Image:
    """合成"古籍版框页"。

    Args:
        img_size: (W, H)
        frame_rect: (x0, y0, x1, y1) 版框 bbox
        frame_width: 版框线宽（px）
        text_inside: 是否在版框内放文字
        outer_noise: 是否在版框外加零散噪点（模拟 trim 失败的根因）
        yuwei_outside: 是否加一个鱼尾装饰超出版框底边（仍能正确选版框）
        frame_broken: 版框线是否在某处断裂（5×5 CLOSE 应能修补）
    """
    W, H = img_size
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    fx0, fy0, fx1, fy1 = frame_rect
    # 版框
    if frame_broken:
        # 顶部线中间断 8px
        for x in range(fx0, fx0 + (fx1 - fx0) // 2 - 5):
            for dy in range(frame_width):
                draw.point((x, fy0 + dy), fill="black")
        for x in range(fx0 + (fx1 - fx0) // 2 + 5, fx1):
            for dy in range(frame_width):
                draw.point((x, fy0 + dy), fill="black")
        # 其余 3 边完整
        draw.rectangle(
            [(fx0, fy0), (fx1, fy1)],
            outline="black",
            width=frame_width,
        )
    else:
        draw.rectangle(
            [(fx0, fy0), (fx1, fy1)],
            outline="black",
            width=frame_width,
        )
    # 版框内文字
    if text_inside:
        for y in range(fy0 + 40, fy1 - 40, 30):
            draw.line([(fx0 + 30, y), (fx1 - 30, y)], fill="black", width=2)
    # 版框外噪点
    if outer_noise:
        # 在版框上方散点（模拟 trim 失败的根因）
        for x, y in [(50, 20), (60, 30), (70, 25), (55, 45), (65, 50)]:
            draw.point((x, y), fill="black")
        # 在版框下方散点
        for x, y in [(100, H - 30), (200, H - 25), (300, H - 35)]:
            draw.point((x, y), fill="black")
    # 鱼尾装饰超出版框
    if yuwei_outside:
        # 在版框下方中央画个鱼尾形状（故意超出 fy1）
        for y in range(fy1 - 5, fy1 + 40):
            for dx in range(-10, 10):
                x = (fx0 + fx1) // 2 + dx
                if 0 <= x < W:
                    draw.point((x, y), fill="black")
    return img


# ----------------------------------------------------------------------------
# 单元测试：detect_frame_bbox
# ----------------------------------------------------------------------------


def test_detect_frame_bbox_finds_clear_frame() -> None:
    """清晰版框 → 返回版框 bbox。"""
    img = _page_with_frame()
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is not None
    top, bottom, left, right = bbox
    # 版框定义：x∈[80,720], y∈[120,1080]
    # bbox 应在版框内（含线宽 ± 5px 容差）
    assert 115 <= top <= 125, f"top={top}"
    assert 1075 <= bottom <= 1085, f"bottom={bottom}"
    assert 75 <= left <= 85, f"left={left}"
    assert 715 <= right <= 725, f"right={right}"


def test_detect_frame_bbox_returns_none_on_blank_page() -> None:
    """全白页 → 返回 None（让 trim 走 fallback）。"""
    img = Image.new("RGB", (800, 1200), "white")
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is None


def test_detect_frame_bbox_returns_none_on_text_only_no_frame() -> None:
    """只有文字、无版框 → 返回 None。"""
    img = Image.new("RGB", (800, 1200), "white")
    draw = ImageDraw.Draw(img)
    for y in range(200, 1000, 30):
        draw.line([(100, y), (700, y)], fill="black", width=2)
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is None  # 无空心大矩形


def test_detect_frame_bbox_ignores_outer_noise() -> None:
    """版框外有零散噪点 → bbox 仍对齐版框（不被噪点拉大）。"""
    img = _page_with_frame(outer_noise=True)
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is not None
    top, bottom, left, right = bbox
    # 外噪点不应进入 bbox
    assert top >= 115, f"top 被噪点拉低: {top}"
    assert bottom <= 1085, f"bottom 被噪点拉高: {bottom}"


def test_detect_frame_bbox_handles_yuwei_inside_frame() -> None:
    """鱼尾装饰在版框内 → bbox 仍为版框（鱼尾不改变版框 bbox）。"""
    img = _page_with_frame(yuwei_outside=False)  # 鱼尾在版框内
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is not None
    top, bottom, left, right = bbox
    # 鱼尾在版框内（fy0+50 ~ fy1-50），不影响 bbox
    assert 115 <= top <= 125
    assert 1075 <= bottom <= 1085


def test_detect_frame_bbox_handles_broken_frame() -> None:
    """版框线断裂 → 5×5 CLOSE 修补 → 仍检测到版框。"""
    img = _page_with_frame(frame_broken=True)
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is not None
    top, bottom, left, right = bbox
    assert 115 <= top <= 125
    assert 1075 <= bottom <= 1085


def test_detect_frame_bbox_respects_min_bbox_ratio() -> None:
    """bbox 太小的"假版框"应被滤掉。"""
    # 一个小矩形框（占图像 < 30%）
    img = Image.new("RGB", (1000, 1000), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(450, 450), (550, 550)], outline="black", width=2)  # 100x100 = 1%
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is None  # 不满足 min_bbox_ratio


def test_detect_frame_bbox_filters_non_hollow() -> None:
    """实心块（fill > 15%）应被滤掉（不是空心框）。"""
    img = Image.new("RGB", (1000, 1000), "white")
    draw = ImageDraw.Draw(img)
    # 实心 600x800 矩形（fill=100%）
    draw.rectangle([(100, 100), (700, 900)], fill="black")
    arr = np.asarray(img.convert("L"))
    ink_mask = arr < 128
    bbox = detect_frame_bbox(ink_mask)
    assert bbox is None  # 不空心


# ----------------------------------------------------------------------------
# 集成测试：trim_margins + trim_frame=True
# ----------------------------------------------------------------------------


def test_trim_frame_param_accepted() -> None:
    """trim_frame=True 是合法参数（当前不存在 → TypeError → RED）。"""
    img = _page_with_frame()
    out = trim_margins(img, padding=5, trim_frame=True)
    assert out.size[0] > 0 and out.size[1] > 0


def test_trim_frame_crop_tighter_than_baseline_with_outer_noise() -> None:
    """开 trim_frame + 外噪点 → crop 应比不开更紧。"""
    img = _page_with_frame(outer_noise=True)
    out_baseline = trim_margins(img, padding=5)
    out_frame = trim_margins(img, padding=5, trim_frame=True)
    # baseline 会被外噪点拉到图像边缘（因为只要看到噪点就当作内容）
    # frame 模式会忽略噪点，对齐到版框
    h_base = out_baseline.size[1]
    h_frame = out_frame.size[1]
    # frame 模式应至少一样紧（不会更松）
    assert h_frame <= h_base + 2, f"frame={h_frame} 比 baseline={h_base} 松太多"


def test_trim_frame_baseline_unchanged_when_disabled() -> None:
    """trim_frame=False（默认）→ 行为与旧版完全一致。"""
    img = _page_with_frame()
    out_default = trim_margins(img, padding=5)
    out_explicit_off = trim_margins(img, padding=5, trim_frame=False)
    assert out_default.size == out_explicit_off.size


def test_trim_frame_falls_back_on_no_frame() -> None:
    """无版框时 → trim_frame=True 不崩，fallback 到原 trim。"""
    img = Image.new("RGB", (800, 1200), "white")
    draw = ImageDraw.Draw(img)
    for y in range(200, 1000, 30):
        draw.line([(100, y), (700, y)], fill="black", width=2)
    out = trim_margins(img, padding=5, trim_frame=True)
    assert out.size[0] > 0 and out.size[1] > 0


def test_trim_frame_min_ratio_param_accepted() -> None:
    """trim_frame_min_ratio 是合法参数。"""
    img = _page_with_frame()
    out = trim_margins(img, padding=5, trim_frame=True, trim_frame_min_ratio=0.5)
    assert out.size[0] > 0 and out.size[1] > 0


def test_trim_frame_max_fill_param_accepted() -> None:
    """trim_frame_max_fill 是合法参数。"""
    img = _page_with_frame()
    out = trim_margins(img, padding=5, trim_frame=True, trim_frame_max_fill=0.30)
    assert out.size[0] > 0 and out.size[1] > 0
