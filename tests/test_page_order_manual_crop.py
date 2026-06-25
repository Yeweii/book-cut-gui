"""v2.3+ page_order × manual crop is_even 映射测试。

对应 bug：RTL 模式下 split 输出 [左, 右] 后被 flip 成 [右, 左]，
但 is_even = (i == 0) 仍把 array[0]（右物理页）当 even → 奇偶页语义反了。

物理位置真相（与 page_order 无关）：
  - 左物理页：gutter 在右 → even（inner=右 padding, outer=左 padding）
  - 右物理页：gutter 在左 → odd （inner=左 padding, outer=右 padding）

LTR: array = [左, 右] → 左 = i=0 = even
RTL: array = [右, 左] → 左物理页在 i=1 = even
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
import pytest


def _make_split_image(left_marker_x: tuple[int, int], right_marker_x: tuple[int, int]) -> Image.Image:
    """1000×1000 灰图，中央放置左右页标记。

    Args:
        left_marker_x: 左页标记的 x 范围（如 (320, 380)）。
        right_marker_x: 右页标记的 x 范围（1000w 全图坐标，如 (620, 680)）。
    """
    img = np.full((1000, 1000), 128, dtype=np.uint8)
    img[400:600, left_marker_x[0]:left_marker_x[1]] = 0
    img[400:600, right_marker_x[0]:right_marker_x[1]] = 0
    return Image.fromarray(img)


def _run_pipeline(page_order: str, padding: str = "T=0,B=0,I=100,O=300") -> dict[str, np.ndarray]:
    """跑一次半切 + manual crop pipeline，返回 {filename: ndarray}。"""
    import argparse
    import threading

    from book_cut.pipeline.orchestrator import run_pipeline

    with tempfile.TemporaryDirectory() as tmpdir:
        indir = Path(tmpdir) / "in"
        outdir = Path(tmpdir) / "out"
        indir.mkdir()
        # 左右两侧都放标记：左页 320-380，右页 620-680（在 500w 右页 = 120-180）
        _make_split_image((320, 380), (620, 680)).save(indir / "test.png")

        args = argparse.Namespace(
            input=str(indir), output=str(outdir),
            split="half", crop="manual",
            manual_odd_padding=padding,
            manual_even_padding=padding,
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

        return {f.name: np.array(Image.open(f)) for f in sorted(outdir.glob("*.png"))}


def test_ltr_mode_preserves_both_pages():
    """LTR 模式：array=[左,右] → i=0(左)=even 用 arr[outer:w-inner]=arr[300:400]；i=1(右)=odd 用 arr[inner:w-outer]=arr[100:200]。

    左页标记 cols 320-380 → even crop arr[300:400] → cropped cols 20-80
    右页标记（500w 坐标 120-180）→ odd crop arr[100:200] → cropped cols 20-80
    两页都应在 cropped x=[20, 79] 找到黑像素。
    """
    results = _run_pipeline("ltr")
    files = sorted(results.keys())
    assert len(files) == 2, f"expected 2 outputs, got {len(files)}"

    for f in files:
        out = results[f]
        ys, xs = np.where(out == 0)
        assert len(xs) > 0, f"{f}: content should be preserved, got all gray"
        assert xs.min() == 20 and xs.max() == 79, (
            f"{f}: bbox x=[{xs.min()},{xs.max()}] expected [20, 79]"
        )


def test_rtl_mode_preserves_both_pages():
    """RTL 模式：array=[右,左]（flip 后）→ i=0(右)=odd, i=1(左)=even。

    修复前 bug：i=0 被当 even → 右页被错切（inner=右 pad 套在 gutter=左 侧）
    → 右页标记丢失。修复后 i=0 用 odd → arr[100:200]，标记保留。
    """
    results = _run_pipeline("rtl")
    files = sorted(results.keys())
    assert len(files) == 2, f"expected 2 outputs, got {len(files)}"

    for f in files:
        out = results[f]
        ys, xs = np.where(out == 0)
        assert len(xs) > 0, f"{f}: content should be preserved (RTL fix), got all gray"
        assert xs.min() == 20 and xs.max() == 79, (
            f"{f}: bbox x=[{xs.min()},{xs.max()}] expected [20, 79] "
            f"（修复前 RTL 模式下 in_0001 会是 all gray，因为右物理页被错套 even 公式）"
        )


def test_ltr_and_rtl_output_geometry_identical():
    """LTR 和 RTL 应产生几何对称的输出（同一物理位置的内容被保留到同一 cropped 位置）。

    修复前：LTR 输出含内容，RTL 输出 all gray（crop 错位）。
    修复后：两者都含内容，且 cropped bbox 位置相同。
    """
    ltr = _run_pipeline("ltr")
    rtl = _run_pipeline("rtl")

    for ltr_file, rtl_file in zip(sorted(ltr.keys()), sorted(rtl.keys())):
        ltr_out = ltr[ltr_file]
        rtl_out = rtl[rtl_file]
        assert ltr_out.shape == rtl_out.shape, (
            f"{ltr_file} vs {rtl_file}: shape mismatch {ltr_out.shape} vs {rtl_out.shape}"
        )
        # 两边的黑像素分布应一致（说明物理位置映射正确）
        ltr_ys, ltr_xs = np.where(ltr_out == 0)
        rtl_ys, rtl_xs = np.where(rtl_out == 0)
        assert (ltr_xs.min(), ltr_xs.max()) == (rtl_xs.min(), rtl_xs.max()), (
            f"LTR bbox x=[{ltr_xs.min()},{ltr_xs.max()}] vs "
            f"RTL bbox x=[{rtl_xs.min()},{rtl_xs.max()}] 不一致"
        )