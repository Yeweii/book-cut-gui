"""v2.3.1+ 单页输入（split=none）+ manual crop 的奇偶页判定测试。

对应 bug：split=none 时 sub_arrs=[arr]（单元素），原来的 `is_even = (i == 0)`
让所有页都被当成 even，odd profile 配置完全没被用到。

修复：split=none 时改用全局页号（1-based，奇数页=odd，偶数页=even）。

测试策略：每个输入页有同样的中央标记；用同样的 odd/even padding 值
（I=200, O=0），靠 v2.3 公式的 inner/outer 物理侧互换产生不同的 crop 范围：
  odd  page (gutter 在左)：arr[inner:w-outer]      = arr[200:800] → marker 100-299
  even page (gutter 在右)：arr[outer:w-inner]      = arr[0:600]   → marker 300-499
通过 cropped marker 位置判断哪个 profile 被应用。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
import pytest


def _make_page_with_center_marker() -> Image.Image:
    """800×1000 单页，cols 300-500 放黑标记（用于判断哪个 profile 被应用）。"""
    img = np.full((1000, 800), 128, dtype=np.uint8)
    img[400:600, 300:500] = 0
    return Image.fromarray(img)


def _run_pipeline(input_count: int, page_order: str = "ltr") -> list[np.ndarray]:
    """跑 N 张单页输入 + manual crop pipeline，返回按 counter 顺序的输出列表。"""
    import argparse
    import threading

    from book_cut.pipeline.orchestrator import run_pipeline

    with tempfile.TemporaryDirectory() as tmpdir:
        indir = Path(tmpdir) / "in"
        outdir = Path(tmpdir) / "out"
        indir.mkdir()
        for i in range(input_count):
            _make_page_with_center_marker().save(indir / f"page_{i + 1:03d}.png")

        args = argparse.Namespace(
            input=str(indir), output=str(outdir),
            split="none",
            crop="manual",
            # 同样的 (I=200, O=0) — 靠 v2.3 公式的 inner/outer 物理侧互换区分奇偶：
            #   odd  → arr[inner:w-outer]    = arr[200:800]   marker 100-299
            #   even → arr[outer:w-inner]    = arr[0:600]     marker 300-499
            manual_odd_padding="T=0,B=0,I=200,O=0",
            manual_even_padding="T=0,B=0,I=200,O=0",
            manual_mirror_even=None, manual_preset=None, manual_save_preset=None,
            format="png", pdf=False, pdf_page_size="A4", pdf_page_dim="210x297", pdf_page_unit="mm",
            binarize="none", deskew=False, no_morph=True, outline=False,
            dry_run=False, sample_n=3, preview_output=None,
            preprocess=[], preprocess_quality="balanced",
            paper=None, paper_force=False,
            page_order=page_order,
        )
        cancel = threading.Event()
        run_pipeline(args, cancel_event=cancel)

        return [np.array(Image.open(f)) for f in sorted(outdir.glob("*.png"))]


def _marker_x_range(out: np.ndarray) -> tuple[int, int] | None:
    """返回 cropped 输出里 marker（黑像素）的 x 范围；不存在则 None。"""
    ys, xs = np.where(out == 0)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(xs.max()))


def test_odd_page_applies_odd_profile():
    """第 1 页（奇数）→ 应用 odd profile → marker 出现在 cropped x=[100, 299]。

    odd profile (I=200,O=0) → arr[200:800] (600 wide, indexed 0..599)
    原图 marker cols 300-500 → cropped cols 100..299
    """
    results = _run_pipeline(input_count=1)
    assert len(results) == 1
    xrange = _marker_x_range(results[0])
    assert xrange is not None, "page 1 (odd) should preserve center marker"
    assert xrange == (100, 299), (
        f"page 1 (odd) marker should be at cropped x=[100, 299] (odd profile = arr[200:800]); "
        f"got {xrange}. 修复前 bug：odd profile 完全没被用到。"
    )


def test_even_page_applies_even_profile():
    """第 2 页（偶数）→ 应用 even profile → marker 出现在 cropped x=[300, 499]。"""
    results = _run_pipeline(input_count=2)
    assert len(results) == 2
    xrange = _marker_x_range(results[1])
    assert xrange is not None, "page 2 (even) should preserve center marker"
    assert xrange == (300, 499), (
        f"page 2 (even) marker should be at cropped x=[300, 499] (even profile = arr[0:600]); "
        f"got {xrange}. 修复前 bug：第 2 页被错套 odd profile。"
    )


def test_alternating_pages_4():
    """4 张单页 → odd/even 交替：1=odd, 2=even, 3=odd, 4=even。"""
    results = _run_pipeline(input_count=4)
    assert len(results) == 4

    expected = [
        (1, (100, 299)),  # odd → odd profile
        (2, (300, 499)),  # even → even profile
        (3, (100, 299)),  # odd → odd profile
        (4, (300, 499)),  # even → even profile
    ]
    for i, (page_no, want) in enumerate(expected):
        xrange = _marker_x_range(results[i])
        assert xrange is not None, (
            f"page {page_no} (output {i}): marker missing. 修复前 bug：所有页被当 even，"
            f"奇数页的 odd 配置未应用 → marker 应在 cropped x={want} 但不存在"
        )
        assert xrange == want, (
            f"page {page_no} (output {i}): marker at {xrange}, expected {want} "
            f"({'odd' if page_no % 2 == 1 else 'even'} profile not applied correctly)"
        )


def test_page_order_does_not_affect_single_page_parity():
    """单页输入下，page_order 不影响奇偶页判定（按全局页号走）。

    修复前：page_order='ltr' → 所有页 is_even=True → 全部用 even profile
    修复后：两种 page_order 都按全局页号（1-based）判定奇偶。
    """
    for order in ("ltr", "rtl"):
        results = _run_pipeline(input_count=2, page_order=order)
        r1 = _marker_x_range(results[0])
        r2 = _marker_x_range(results[1])
        assert r1 == (100, 299), f"[{order}] page 1 marker at {r1}, expected (100, 299)"
        assert r2 == (300, 499), f"[{order}] page 2 marker at {r2}, expected (300, 499)"