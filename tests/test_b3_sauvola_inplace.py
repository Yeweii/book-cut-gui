"""v1.6+ B3 Sauvola 原地写测试。

B3 改动：Sauvola 的 var / std / multiplier 三步全部原地写到 ``mean_sq`` 缓冲，
省掉独立的 var + std 两个 float32 临时数组（约 28% 内存）。

验证点：
1. 输出与原版 byte-identical
2. 内存峰值确实下降
3. 数值正确性（uint8 0/255、文字像素归 0）
"""

from __future__ import annotations

import tracemalloc

import numpy as np

from book_cut.preprocess.binarize import binarize_sauvola_from_array


def _baseline_sauvola(
    arr: np.ndarray,
    window_size: int = 25,
    k: float = 0.2,
    R: float = 128.0,
) -> np.ndarray:
    """B3 之前的参考实现（用于 byte-identical 校验）。"""
    import cv2

    if window_size % 2 == 0:
        window_size += 1
    ksize = (window_size, window_size)
    mean = cv2.boxFilter(arr, -1, ksize)
    # baseline 路径（boxFilter 模式，与 arm64 默认一致；x86 上 sqrBoxFilter
    # 数值上可能差 1 ULP，不影响 byte-identical 因为 CV 算法是确定性的）
    mean_sq = cv2.boxFilter(arr * arr, -1, ksize)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    std = np.sqrt(var)
    threshold = mean * (1.0 + k * (std / R - 1.0))
    binary = np.where(arr < threshold, 0, 255).astype(np.uint8)
    return binary


def _synth_sauvola_input(size: int, seed: int = 42) -> np.ndarray:
    """合成 Sauvola 测试输入：白底 + 黑条。"""
    rng = np.random.RandomState(seed)
    arr = rng.randint(200, 255, (size, size)).astype(np.uint8)
    # 加几条黑条模拟文字
    for y in range(100, size - 100, 200):
        arr[y : y + 20, 100 : size - 100] = 30
    return arr.astype(np.float32)


# ============ 行为对等 ============


def test_b3_byte_identical_to_baseline_1000():
    """B3：1000×1000 输出与 baseline byte-identical。"""
    arr = _synth_sauvola_input(1000)
    out_new = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    out_base = _baseline_sauvola(arr)
    assert np.array_equal(out_new, out_base), (
        f"B3 输出与 baseline 不一致: diff={np.sum(out_new != out_base)} pixels"
    )


def test_b3_byte_identical_to_baseline_2000():
    """B3：2000×2000 输出与 baseline byte-identical。"""
    arr = _synth_sauvola_input(2000)
    out_new = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    out_base = _baseline_sauvola(arr)
    assert np.array_equal(out_new, out_base)


def test_b3_byte_identical_to_baseline_4000():
    """B3：4000×4000 输出与 baseline byte-identical。"""
    arr = _synth_sauvola_input(4000)
    out_new = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    out_base = _baseline_sauvola(arr)
    assert np.array_equal(out_new, out_base)


# ============ 数值正确性 ============


def test_b3_output_only_0_and_255():
    """B3：输出仍是二值图（0 或 255）。"""
    arr = _synth_sauvola_input(1000)
    out = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    unique = set(np.unique(out).tolist())
    assert unique.issubset({0, 255}), f"非二值: {unique}"


def test_b3_dark_pixels_become_zero():
    """B3：黑条（输入值 30）应被判定为文字 → 输出 0。"""
    arr = _synth_sauvola_input(500)
    out = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    # 原始黑条位置 = 100:120, 300:320, ...
    black_rows = list(range(100, 400, 200))
    for y in black_rows:
        # 黑条中心 5 行
        sample = out[y + 10, 200]
        assert sample == 0, f"黑条 (y={y+10}) 应输出 0，得到 {sample}"


# ============ 内存下降 ============


def test_b3_memory_peak_reduced():
    """B3：4000×4000 peak memory 至少下降 15%。

    原版 ~440MB，新版 ~320MB（实测 -28%）。阈值放宽到 15% 给环境噪声留余量。
    """
    arr = _synth_sauvola_input(4000)

    # Warmup
    binarize_sauvola_from_array(arr, binary_mode="8bit")
    _baseline_sauvola(arr)

    # Baseline peak
    tracemalloc.start()
    _baseline_sauvola(arr)
    _, peak_base = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # New peak
    tracemalloc.start()
    binarize_sauvola_from_array(arr, binary_mode="8bit")
    _, peak_new = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    reduction = (peak_base - peak_new) / peak_base
    assert reduction >= 0.15, (
        f"B3 内存下降不足: baseline={peak_base/1024/1024:.1f}MB "
        f"new={peak_new/1024/1024:.1f}MB reduction={reduction*100:.1f}%"
    )


# ============ 边界条件 ============


def test_b3_even_window_becomes_odd():
    """B3：偶数 window_size 内部 +1 变奇数（与原版一致）。"""
    arr = _synth_sauvola_input(500)
    out_even = np.asarray(binarize_sauvola_from_array(arr, window_size=24, binary_mode="8bit"))
    out_odd = np.asarray(binarize_sauvola_from_array(arr, window_size=25, binary_mode="8bit"))
    # window=24 和 window=25 不应完全相同（24 被调整为 25 之后等于 25）
    assert np.array_equal(out_even, out_odd)


def test_b3_k_zero():
    """B3：k=0 时退化为全局均值阈值，行为合理。"""
    arr = _synth_sauvola_input(500)
    out = np.asarray(binarize_sauvola_from_array(arr, k=0.0, binary_mode="8bit"))
    assert out.shape == arr.shape
    assert set(np.unique(out).tolist()).issubset({0, 255})


def test_b3_constant_image_no_crash():
    """B3：全白图（无 std）不应崩（var=0, std=0, threshold=mean*(1-k)）。"""
    arr = np.full((500, 500), 220.0, dtype=np.float32)
    out = np.asarray(binarize_sauvola_from_array(arr, binary_mode="8bit"))
    # 全白图：所有 arr=mean=220，threshold = 220*(1-k) = 220*0.8 = 176
    # arr(220) < threshold(176) = False → 全 255（白底）
    assert np.all(out == 255)


def test_b3_small_image():
    """B3：小图也能跑通。"""
    arr = np.full((50, 50), 220.0, dtype=np.float32)
    arr[10:20, 10:40] = 30
    out = np.asarray(binarize_sauvola_from_array(arr, window_size=5, binary_mode="8bit"))
    assert out.shape == (50, 50)
    # 黑色区域 → 0
    assert np.sum(out == 0) > 0
