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
