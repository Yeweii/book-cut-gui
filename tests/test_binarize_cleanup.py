"""v2.3.3+ 二值化后清理（古籍扫描件噪点）测试。

覆盖：
- _morph_open：移除孤立 specks，保留主体笔画
- _drop_small_components：丢 < min_size 黑簇
- _apply_cleanup：dispatch 4 种 mode
- 各 binarize_* 函数 cleanup 参数透传
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from book_cut.preprocess.binarize import (
    BINARIZE_CLEANUP_CHOICES,
    _apply_cleanup,
    _drop_small_components,
    _morph_open,
    binarize,
    binarize_sauvola,
)

# ----------------------------------------------------------------------------
# T1-T4：_morph_open
# ----------------------------------------------------------------------------


def test_t1_morph_open_removes_isolated() -> None:
    """T1：单像素噪点 + 5×5 黑块 → open 后噪点消失，5×5 块完整保留。

    注：morph_open = INV + MORPH_OPEN + INV，5×5 块足够大，
    开运算后形状基本不变（先 erode 再 dilate 抵消）。
    """
    arr = np.full((20, 20), 255, dtype=np.uint8)
    # 2 个孤立单像素噪点（远离 5×5 块）
    arr[1, 1] = 0
    arr[18, 18] = 0
    # 5×5 大块
    arr[8:13, 8:13] = 0
    out = _morph_open(arr, kernel_size=3)
    # 孤立噪点被 open 移除
    assert out[1, 1] == 255, "孤立单像素应被移除"
    assert out[18, 18] == 255, "孤立单像素应被移除"
    # 5×5 块完整保留为黑
    assert (out[8:13, 8:13] == 0).sum() == 25, "5×5 块应完整保留"


def test_t2_morph_open_keeps_solid_block() -> None:
    """T2：8×8 实心块 → open 后完全保留（中心 ≥ 3×3 区域）。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[6:14, 6:14] = 0
    out = _morph_open(arr, kernel_size=3)
    assert (out[6:14, 6:14] == 0).sum() >= 36, "8×8 块核心 6×6 = 36 px 必保留"


def test_t3_morph_open_kernel_size_2() -> None:
    """T3：kernel_size=2 → 移除 1px specks。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    arr[10, 10] = 0
    out = _morph_open(arr, kernel_size=2)
    assert out[5, 5] == 255


def test_t4_morph_open_kernel_size_1_noop() -> None:
    """T4：kernel_size=1 → noop，arr 原样返回。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _morph_open(arr, kernel_size=1)
    assert (out == arr).all()


# ----------------------------------------------------------------------------
# T5-T7：_drop_small_components
# ----------------------------------------------------------------------------


def test_t5_drop_small_removes_isolated() -> None:
    """T5：3 个 1px² specks + 1 个 100px² 方块 → specks 全丢，方块保留。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[2, 2] = 0
    arr[18, 18] = 0
    arr[0, 19] = 0
    # 10×10 = 100 px² 方块
    arr[5:15, 5:15] = 0
    out = _drop_small_components(arr, min_size=4)
    # 3 个孤立 specks 应被丢
    assert out[2, 2] == 255
    assert out[18, 18] == 255
    assert out[0, 19] == 255
    # 10×10 = 1 cluster (100 px²) > 4 保留
    assert out[10, 10] == 0, "大块中心必保留"
    assert out[7, 7] == 0
    assert out[12, 12] == 0


def test_t6_drop_small_threshold() -> None:
    """T6：min_size=8 → 4 像素簇（2×2）丢，10 像素簇（10×1）保留。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    # 2×2 = 4 px²（< 8 应丢）
    arr[2:4, 2:4] = 0
    # 10×1 = 10 px²（≥ 8 应保留）
    arr[10:20, 10] = 0
    out = _drop_small_components(arr, min_size=8)
    assert (out[2:4, 2:4] == 255).all(), "4 px² 簇应被丢"
    assert (out[10:20, 10] == 0).all(), "10 px² 簇应保留"


def test_t7_drop_small_disabled() -> None:
    """T7：min_size=1 → 全保留（noop）。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _drop_small_components(arr, min_size=1)
    assert out[5, 5] == 0


# ----------------------------------------------------------------------------
# T8-T10：_apply_cleanup
# ----------------------------------------------------------------------------


def test_t8_apply_cleanup_none() -> None:
    """T8：cleanup=none → 原样。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _apply_cleanup(arr, "none")
    assert (out == arr).all()


def test_t9_apply_cleanup_morph() -> None:
    """T9：cleanup=morph → 等价于 _morph_open。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _apply_cleanup(arr, "morph")
    assert out[5, 5] == 255  # 孤立 1px 被 open 移除


def test_t10_apply_cleanup_components() -> None:
    """T10：cleanup=components → 等价于 _drop_small_components(min_size=4)。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _apply_cleanup(arr, "components")
    assert out[5, 5] == 255


def test_t11_apply_cleanup_both() -> None:
    """T11：cleanup=both → components + morph。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    arr[5, 5] = 0
    out = _apply_cleanup(arr, "both")
    assert out[5, 5] == 255


def test_t12_apply_cleanup_invalid() -> None:
    """T12：cleanup=xxx → ValueError。"""
    arr = np.full((20, 20), 255, dtype=np.uint8)
    with pytest.raises(ValueError, match="未知"):
        _apply_cleanup(arr, "xxx")  # type: ignore[arg-type]


def test_t13_cleanup_choices() -> None:
    """T13：BINARIZE_CLEANUP_CHOICES 4 项。"""
    assert BINARIZE_CLEANUP_CHOICES == ("none", "morph", "components", "both")


# ----------------------------------------------------------------------------
# T14-T15：cleanup 透传到 binarize_*
# ----------------------------------------------------------------------------


def test_t14_sauvola_cleanup_components() -> None:
    """T14：binarize_sauvola(cleanup='components') 默认丢小 specks。

    构造一张类文字图像：浅灰底 + 多个 6×6 黑块（模拟笔画 + 孤立 1px² 噪点）。
    Sauvola 对均匀大块不友好（thresh=mean 时 arr==mean 不被识别为文字），
    所以用 6×6 而非 100×100。
    """
    arr_img = np.full((200, 200), 220, dtype=np.uint8)  # 浅灰纸
    # 10 个 6×6 黑块（笔画 = 36 px² > 4）模拟文字块
    for cx, cy in [(30, 30), (60, 30), (90, 30), (120, 30), (150, 30),
                    (30, 150), (60, 150), (90, 150), (120, 150), (150, 150)]:
        arr_img[cy - 3:cy + 3, cx - 3:cx + 3] = 0
    # 20 个孤立 1px 噪点（远离黑块）
    noise_pts = [(x, y) for x in range(0, 200, 20) for y in range(0, 200, 20)]
    for x, y in noise_pts:
        if not (25 <= x <= 155 and 25 <= y <= 155):
            arr_img[y, x] = 0
    img = Image.fromarray(arr_img, mode="L")

    out_none = binarize_sauvola(img, cleanup="none")
    out_comp = binarize_sauvola(img, cleanup="components")

    arr_none = np.array(out_none.convert("L"))
    arr_comp = np.array(out_comp.convert("L"))

    # 总黑像素数：components 应少于 none（噪点被清）
    black_none = int((arr_none == 0).sum())
    black_comp = int((arr_comp == 0).sum())
    assert black_comp < black_none, (
        f"components 应清除噪点：none={black_none}, comp={black_comp}"
    )
    # 且大块应保留 ≥ 80%（允许多个簇共享一个连通域）
    block_pixels_comp = int((arr_comp[25:175, 25:175] == 0).sum())
    assert block_pixels_comp >= 300, f"大块被过度清理: {block_pixels_comp}"


def test_t15_dispatcher_cleanup_passthrough() -> None:
    """T15：binarize(cleanup=...) 透传到具体函数。"""
    img = Image.new("L", (50, 50), 200)
    arr_img = np.array(img)
    arr_img[10:40, 10:40] = 0
    arr_img[0, 0] = 0
    arr_img[49, 49] = 0
    img = Image.fromarray(arr_img, mode="L")

    out = binarize(img, method="sauvola", cleanup="components")
    assert out.mode == "1"  # 默认 1bit
    arr = np.array(out.convert("L"))
    # 大块保留
    assert (arr[10:40, 10:40] == 0).sum() >= 800
    # 角点噪点应清
    assert arr[0, 0] == 255
    assert arr[49, 49] == 255
