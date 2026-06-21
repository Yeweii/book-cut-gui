"""性能基准测试（v1.5+ 优化 backlog 项 D1）。

目的：量化"sauvola 耗时 + 内存"，让 A1/A2/B1 等优化的效果可量化、未来回归可检测。

设计原则：
- **宽松阈值**（当前 30x 余量）：只捕"严重退化"（5x 慢），不抓微小波动（CI 抖动）
- **打印实测耗时**：用 ``-s`` flag 看具体数字
- **不动现有 65 个 test**：纯增量
- **可跳过**：``pytest -m 'not perf'`` 跳过

跑法::

    .venv/bin/pytest tests/test_perf.py -v -s
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from PIL import Image

from book_cut.preprocess.binarize import binarize_sauvola

pytestmark = pytest.mark.perf


def _synth_double_page(size: int = 2000) -> Image.Image:
    """合成一张 ``size x size`` 的双页 RGB 图（中缝白，两侧"文字"）。

    用偏黄纸色（220）+ 黑色笔画（30）模拟古籍扫描件。
    """
    arr = np.full((size, size, 3), 220, dtype=np.uint8)
    # 左页文字（x < size/2 - 20）
    mid = size // 2
    for y in range(100, size - 100, 30):
        for x_start in range(100, mid - 50, 60):
            arr[y:y + 10, x_start:x_start + 40] = 30
    # 右页文字
    for y in range(100, size - 100, 30):
        for x_start in range(mid + 50, size - 100, 60):
            arr[y:y + 10, x_start:x_start + 40] = 30
    return Image.fromarray(arr, mode="RGB")


def test_binarize_sauvola_2000_perf():
    """Sauvola 2000×2000 RGB 性能基准。

    平台默认后端（v1.5+ A2 平台后端选择）：
    - arm64：boxFilter（NEON 优化）~ 15-17ms
    - x86_64：sqrBoxFilter（AVX fused）~ 15-20ms（推测）
    阈值 500ms 留 30x 余量，仅作退化检测用。
    """
    img = _synth_double_page(2000)
    # 热身：避免首次 JIT 编译 / cache miss 影响
    binarize_sauvola(img)

    t = time.perf_counter()
    out = binarize_sauvola(img)
    elapsed_ms = (time.perf_counter() - t) * 1000

    print(f"\n[binarize_sauvola 2000x2000] {elapsed_ms:.1f}ms")
    assert out.size == img.size
    assert elapsed_ms < 500, f"性能退化：{elapsed_ms:.1f}ms > 500ms"


def test_binarize_sauvola_4000_perf():
    """Sauvola 4000×4000 RGB 性能基准（接近真实古籍扫描件尺寸）。

    平台默认后端（v1.5+ A2 平台后端选择）：
    - arm64：boxFilter（NEON 优化）~ 60-70ms
    - x86_64：sqrBoxFilter（AVX fused）~ 50-70ms（推测）
    阈值 800ms 留 10x 余量（冷启动 + 大图 = 显著开销）。
    """
    img = _synth_double_page(4000)
    binarize_sauvola(img)  # 热身

    t = time.perf_counter()
    out = binarize_sauvola(img)
    elapsed_ms = (time.perf_counter() - t) * 1000

    print(f"\n[binarize_sauvola 4000x4000] {elapsed_ms:.1f}ms")
    assert out.size == img.size
    assert elapsed_ms < 800, f"性能退化：{elapsed_ms:.1f}ms > 800ms"


# ----------------------------------------------------------------------------
# v1.5+ A1：全流水线性能（单次 RGB→L 转换）
# ----------------------------------------------------------------------------


def test_pipeline_full_perf_4000():
    """全流水线 4000×4000 RGB 性能基准（v1.5+ A1 量化）。

    流水线：deskew=False + split gutter + crop border + binarize sauvola
    v1.4 baseline：~160ms/页（每页 5 次 convert("L")）
    v1.5+ A1 目标：~145ms/页（单次 convert，余 4 次消除，省 10%）
    阈值 500ms 留 3x 余量（仅作退化检测）。
    """
    from book_cut.preprocess.binarize import binarize_sauvola_from_array
    from book_cut.split.gutter import split_gutter_from_array
    from book_cut.detect.border import crop_to_border_from_array

    img = _synth_double_page(4000)
    # 热身
    arr = np.asarray(img.convert("L"))
    sub_arrs = split_gutter_from_array(arr, auto_single_page=False)
    _ = crop_to_border_from_array(sub_arrs[0], padding=10)
    _ = binarize_sauvola_from_array(sub_arrs[0].astype(np.float32))

    t = time.perf_counter()
    # A1 全流水线（arr 路径）
    arr = np.asarray(img.convert("L"))  # ← 唯一一次 RGB→L
    sub_arrs = split_gutter_from_array(arr, auto_single_page=False)
    for sub in sub_arrs:
        cropped = crop_to_border_from_array(sub, padding=10)
        _ = binarize_sauvola_from_array(np.asarray(cropped.convert("L"), dtype=np.float32))
    elapsed_ms = (time.perf_counter() - t) * 1000

    print(f"\n[pipeline full 4000x4000 A1] {elapsed_ms:.1f}ms")
    assert elapsed_ms < 500, f"性能退化：{elapsed_ms:.1f}ms > 500ms"


# ----------------------------------------------------------------------------
# v1.5+ A1：行为对等（公共 API vs ``*_from_array``）
# ----------------------------------------------------------------------------


def test_trim_margins_from_array_matches_public():
    """trim 公共 API 与 ``_trim_margins_from_array`` 输出像素一致（A1 行为对等）。"""
    from book_cut.detect.trim import _trim_margins_from_array, trim_margins

    img = _synth_double_page(400)
    arr = np.asarray(img.convert("L"))

    out_public = np.asarray(trim_margins(img))
    out_from_arr = np.asarray(_trim_margins_from_array(arr))

    assert out_public.shape == out_from_arr.shape
    assert np.array_equal(out_public, out_from_arr), "公共 API 与 _from_array 像素不一致"


def test_binarize_sauvola_from_array_matches_public():
    """binarize_sauvola 公共 API 与 ``binarize_sauvola_from_array`` 输出一致（A1）。"""
    from book_cut.preprocess.binarize import (
        binarize_sauvola,
        binarize_sauvola_from_array,
    )

    img = _synth_double_page(400)
    arr = np.asarray(img.convert("L"), dtype=np.float32)

    out_public = np.asarray(binarize_sauvola(img))
    out_from_arr = np.asarray(binarize_sauvola_from_array(arr))

    assert out_public.shape == out_from_arr.shape
    assert np.array_equal(out_public, out_from_arr), "公共 API 与 _from_array 像素不一致"
