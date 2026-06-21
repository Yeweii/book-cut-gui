"""C1 共享 Hough 模块测试。

验证：
- canny_edges / detect_lines / cluster_lines 公共 API 工作正常
- 3 个 preset（deskew / split_border / crop_border）参数各跑得通
- 行为与原 inline 实现一致（canny 像素一致，line 数量 ≥ 内联）
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from book_cut.detect._hough import (
    HOUGH_PRESET_CROP_BORDER,
    HOUGH_PRESET_DESKEW,
    HOUGH_PRESET_SPLIT_BORDER,
    canny_edges,
    cluster_lines,
    detect_lines,
)

# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def _border_image(size: tuple[int, int] = (400, 300)) -> Image.Image:
    """合成一张 400x300 的图：左版框 + 右版框 + 一些文字线。"""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    # 左版框：(40, 40) - (180, 260)
    draw.rectangle([(40, 40), (180, 260)], outline="black", width=2)
    # 右版框：(220, 40) - (360, 260)
    draw.rectangle([(220, 40), (360, 260)], outline="black", width=2)
    return img


# ----------------------------------------------------------------------------
# T1: canny_edges 等价 cv2.Canny
# ----------------------------------------------------------------------------


def test_canny_edges_matches_cv2_directly():
    """``canny_edges`` 直接调 cv2.Canny，行为一致。"""
    img = _border_image()
    arr = np.asarray(img.convert("L"))

    out_helper = canny_edges(arr)
    out_inline = cv2.Canny(arr, 50, 150)

    assert np.array_equal(out_helper, out_inline)


# ----------------------------------------------------------------------------
# T2: detect_lines 3 个 preset 都跑通
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preset",
    [
        HOUGH_PRESET_DESKEW,
        HOUGH_PRESET_SPLIT_BORDER,
        HOUGH_PRESET_CROP_BORDER,
    ],
    ids=["deskew", "split_border", "crop_border"],
)
def test_detect_lines_all_presets_find_lines(preset):
    """3 个 preset 在带边框图上都能找到 Hough 直线。"""
    img = _border_image()
    arr = np.asarray(img.convert("L"))

    lines = detect_lines(arr, **preset)
    assert lines is not None
    assert len(lines) > 0
    # 每条线 4 个 int 坐标
    for line in lines:
        assert len(line) == 4
        assert all(isinstance(v, int) for v in line)


# ----------------------------------------------------------------------------
# T3: cluster_lines 正确合并相邻
# ----------------------------------------------------------------------------


def test_cluster_lines_merges_close_verticals():
    """相邻竖线合并到同一簇（中位数）。"""
    lines = [
        (100, 0, 100, 100),  # vertical at x=100
        (101, 0, 101, 100),  # vertical at x=101
        (102, 0, 102, 100),  # vertical at x=102 → cluster median = 101
        (200, 0, 200, 100),  # vertical at x=200 (far away, separate cluster)
    ]
    vs, hs = cluster_lines(lines)
    # 预期：[101, 200]
    assert vs == [101, 200]
    assert hs == []


def test_cluster_lines_horizontals_separate():
    """横线 vs 竖线分开聚类。"""
    lines = [
        (0, 50, 100, 50),  # horizontal at y=50
        (0, 51, 100, 51),  # horizontal at y=51
        (50, 0, 50, 100),  # vertical at x=50
    ]
    vs, hs = cluster_lines(lines)
    assert vs == [50]
    assert hs == [50] or hs == [51]  # cluster median ±0.5


def test_cluster_lines_empty():
    """空输入返 ``([], [])``."""
    vs, hs = cluster_lines([])
    assert vs == []
    assert hs == []


# ----------------------------------------------------------------------------
# T4: detect_lines 行为对等（与原 inline 实现比较）
# ----------------------------------------------------------------------------


def test_detect_lines_equivalent_to_inline_split_border():
    """``detect_lines(arr, **HOUGH_PRESET_SPLIT_BORDER)`` 与原 inline 等价。"""
    img = _border_image()
    arr = np.asarray(img.convert("L"))

    # 新：调共享 detect_lines
    new_lines = detect_lines(arr, **HOUGH_PRESET_SPLIT_BORDER)

    # 旧：模拟原 inline 实现
    edges = cv2.Canny(arr, 50, 150)
    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(20, arr.shape[1] // 20),
        maxLineGap=10,
    )
    assert raw is not None
    old_lines = [(int(x1), int(y1), int(x2), int(y2)) for x1, y1, x2, y2 in raw[:, 0]]

    # 两者 line 集合应一致（顺序可能不同，转 set 比较）
    assert set(new_lines) == set(old_lines)


def test_detect_lines_equivalent_to_inline_crop_border():
    """crop_border preset 等价原 inline。"""
    img = _border_image()
    arr = np.asarray(img.convert("L"))

    new_lines = detect_lines(arr, **HOUGH_PRESET_CROP_BORDER)

    edges = cv2.Canny(arr, 50, 150)
    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=60,
        minLineLength=max(20, arr.shape[1] // 30),
        maxLineGap=8,
    )
    assert raw is not None
    old_lines = [(int(x1), int(y1), int(x2), int(y2)) for x1, y1, x2, y2 in raw[:, 0]]

    assert set(new_lines) == set(old_lines)
