"""v1.8 dry-run 流水线：仅采样 + 渲染预览，不写盘。

从 ``orchestrator.py`` 拆出（v1.8+ C3 续）—— 让 orchestrator 保持 < 500 行。
"""

from __future__ import annotations

import tempfile
import time
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from book_cut.io.loader import PageInfo


def run_dry_run(
    *,
    first_page: PageInfo,
    full_iter,
    sampled_remaining: int,
    sample_n: int,
    preview_dir: Path | None,
    input_path: Path,
    deskew_enabled: bool,
    auto_single_page: bool,
    page_order: str,
    crop_mode: str,
    binarize_method: str,
    crop_config,
    paper_deviation: float,
    split_strategy: str,
    half_offset: int,
    use_morph: bool,
) -> None:
    """跑 dry-run：处理前 sample_n 页 + 渲染预览 + 写 summary。

    副作用：写预览到 ``preview_dir``（或 tmpdir），不创建 ``output_dir``，不写图，不生成 PDF。
    """
    from book_cut.pipeline.orchestrator import _compute_page
    from book_cut.pipeline.preview import (
        compute_summary,
        render_compare,
        write_preview,
    )

    # 收集前 sample_n 页（first_page + 后续 N-1）
    sample_results: list[dict] = []
    first_result = _compute_page(
        first_page,
        deskew_enabled=deskew_enabled,
        auto_single_page=auto_single_page,
        page_order=page_order,
        crop_mode=crop_mode,
        binarize_method=binarize_method,
        crop_config=crop_config,
        paper_deviation=paper_deviation,
        split_strategy=split_strategy,
        half_offset=half_offset,
        use_morph=use_morph,
        is_sampled_page=True,
    )
    sample_results.append(first_result)

    for i, page in enumerate(islice(full_iter, sample_n - 1)):
        result = _compute_page(
            page,
            deskew_enabled=deskew_enabled,
            auto_single_page=auto_single_page,
            page_order=page_order,
            crop_mode=crop_mode,
            binarize_method=binarize_method,
            crop_config=crop_config,
            paper_deviation=paper_deviation,
            split_strategy=split_strategy,
            half_offset=half_offset,
            use_morph=use_morph,
            is_sampled_page=(i < sampled_remaining),
        )
        sample_results.append(result)

    # 决定预览目录
    out_preview_dir = (
        preview_dir
        if preview_dir is not None
        else Path(tempfile.gettempdir()) / f"book-cut-preview-{int(time.time())}"
    )

    # 渲染每页拼图
    compare_images: list[tuple[int, Image.Image]] = []
    for r in sample_results:
        original = r["original"]
        sub_pages = r["sub_pages"]
        left = sub_pages[0] if len(sub_pages) > 0 else None
        right = sub_pages[1] if len(sub_pages) > 1 else None
        meta = {
            "source": r["metrics"]["source"],
            "page_idx": r["metrics"]["page_idx"],
            "split_x": r["metrics"]["split"]["x"],
            "deskew_angle": r["metrics"]["deskew"].get("angle"),
            "size_in": r["metrics"]["size_in"],
            "size_left": r["metrics"]["split"]["size_left"],
            "size_right": r["metrics"]["split"]["size_right"],
        }
        compare_img = render_compare(original, left, right, meta)
        compare_images.append((r["metrics"]["page_idx"], compare_img))

    # 计算 elapsed + 汇总
    pages_metrics = [r["metrics"] for r in sample_results]
    total_ms = sum(sum(m["timings_ms"].values()) for m in pages_metrics)
    per_page_avg = total_ms / max(1, len(pages_metrics))
    sample_indices = [r["metrics"]["page_idx"] for r in sample_results]

    summary = compute_summary(
        input_path=input_path,
        config={
            "split": split_strategy,
            "crop": crop_mode,
            "binarize": binarize_method,
            "deskew": deskew_enabled,
            "page_order": page_order,
        },
        sample_indices=sample_indices,
        total_pages=max(1, len(sample_results)),
        pages_metrics=pages_metrics,
        elapsed_ms={
            "total": round(total_ms, 1),
            "per_page_avg": round(per_page_avg, 1),
            "estimated_full": round(per_page_avg * 130, 1),
        },
        paper_color=None,
    )

    write_preview(out_preview_dir, compare_images, pages_metrics, summary)
    print(
        f"[OK] dry-run 完成：采样 {len(sample_results)} 页 → {out_preview_dir}\n"
        f"     对比图: preview_p*_compare.png × {len(compare_images)}\n"
        f"     指标: preview_summary.json"
    )
