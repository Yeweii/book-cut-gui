"""v1.8 dry-run 流水线：仅采样 + 渲染预览，不写盘。

从 ``orchestrator.py`` 拆出（v1.8+ C3 续）—— 让 orchestrator 保持 < 500 行。
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from book_cut.io.loader import PageInfo


# v2.3.5+：dry-run 旧预览目录前缀
_PREVIEW_DIR_PREFIX = "book-cut-preview-"

# v2.3.5+：dry-run 旧预览目录最大保留天数（超期自动删，避免 tmpdir 累积）
DEFAULT_PREVIEW_MAX_AGE_DAYS = 7


def cleanup_old_previews(
    max_age_days: int = DEFAULT_PREVIEW_MAX_AGE_DAYS,
    tmpdir: Path | None = None,
) -> int:
    """清理 tmpdir 下超期的 book-cut-preview-* 目录（v2.3.5+）。

    Args:
        max_age_days: 保留天数（默认 7），超期删除
        tmpdir: 扫描根目录（默认 ``tempfile.gettempdir()``）

    Returns:
        删除的目录数。

    Why:
        之前 dry-run 每次都在 tmpdir 留一个新目录（``book-cut-preview-{ts}``），
        跑多了会累积（实测 2 天留 2 个 ≈ 4MB）。每次新 dry-run 前扫一遍旧目录
        —— 是无副作用的卫生清理，不需要 opt-in。
    """
    root = Path(tmpdir) if tmpdir is not None else Path(tempfile.gettempdir())
    if not root.is_dir():
        return 0
    now = time.time()
    max_age_sec = max_age_days * 86400
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if not entry.name.startswith(_PREVIEW_DIR_PREFIX):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) > max_age_sec:
            try:
                shutil.rmtree(entry)
                removed += 1
            except OSError:
                pass  # best-effort：清不掉就跳过
    return removed



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
    binary_mode: str = "1bit",
    binarize_cleanup: str = "components",  # v2.3.3+
    crop_config,
    paper_deviation: float,
    split_strategy: str,
    half_offset: int,
    use_morph: bool,
    preprocess_chain: list[str] | None = None,
    preprocess_quality: str = "balanced",
    trim_source: str = "gray",
    min_component_ratio: float = 0.0,
    extra_padding: int = 0,
    gutter_band: tuple[float, float] | None = None,
    gutter_bands: list[tuple[float, float]] | None = None,
    horizontal: bool = True,
    trim_strict: bool = False,
    trim_frame: bool = False,
    trim_frame_min_ratio: float = 0.30,
    trim_frame_max_fill: float = 0.15,
    cancel_event: threading.Event | None = None,
) -> None:
    """跑 dry-run：处理前 sample_n 页 + 渲染预览 + 写 summary。

    副作用：写预览到 ``preview_dir``（或 tmpdir），不创建 ``output_dir``，不写图，不生成 PDF。
    """
    # v2.3.5+：先扫一遍 tmpdir 旧预览目录（>7 天自动删，避免累积）
    cleanup_old_previews()

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
        binary_mode=binary_mode,
        binarize_cleanup=binarize_cleanup,
        crop_config=crop_config,
        paper_deviation=paper_deviation,
        split_strategy=split_strategy,
        half_offset=half_offset,
        use_morph=use_morph,
        is_sampled_page=True,
        global_page_no=1,
        preprocess_chain=preprocess_chain,
        preprocess_quality=preprocess_quality,
        trim_source=trim_source,
        min_component_ratio=min_component_ratio,
        extra_padding=extra_padding,
        gutter_band=gutter_band,
        gutter_bands=gutter_bands,
        horizontal=horizontal,
        trim_strict=trim_strict,
        trim_frame=trim_frame,
        trim_frame_min_ratio=trim_frame_min_ratio,
        trim_frame_max_fill=trim_frame_max_fill,
    )
    sample_results.append(first_result)

    cancelled = False
    for i, page in enumerate(islice(full_iter, sample_n - 1)):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            print(f"[INFO] 用户取消：dry-run 采样在第 {i + 1} 页边界停止")
            break
        result = _compute_page(
            page,
            deskew_enabled=deskew_enabled,
            auto_single_page=auto_single_page,
            page_order=page_order,
            crop_mode=crop_mode,
            binarize_method=binarize_method,
            binary_mode=binary_mode,
            binarize_cleanup=binarize_cleanup,
            crop_config=crop_config,
            paper_deviation=paper_deviation,
            split_strategy=split_strategy,
            half_offset=half_offset,
            use_morph=use_morph,
            is_sampled_page=(i < sampled_remaining),
            global_page_no=i + 2,
            preprocess_chain=preprocess_chain,
            preprocess_quality=preprocess_quality,
            trim_source=trim_source,
            min_component_ratio=min_component_ratio,
            extra_padding=extra_padding,
            gutter_band=gutter_band,
            gutter_bands=gutter_bands,
            horizontal=horizontal,
            trim_strict=trim_strict,
            trim_frame=trim_frame,
            trim_frame_min_ratio=trim_frame_min_ratio,
            trim_frame_max_fill=trim_frame_max_fill,
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
        raw_original = r.get("raw_original")  # v1.9+：preprocess 前的真·原始
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
            # v1.9+：preprocess 元数据
            "preprocess_chain": r["metrics"].get("preprocess", {}).get("chain", []),
            "preprocess_quality": r["metrics"].get("preprocess", {}).get("quality", ""),
        }
        # v1.9+：当启用 preprocess 时，把"preprocess 后、deskew 前"的图作为 PREPROCESS 列
        preprocessed = original if meta["preprocess_chain"] else None
        # ORIGINAL 列：v1.9+ 用 raw_original（preprocess 前）；无 raw_original 则回退
        compare_img = render_compare(
            raw_original if raw_original is not None else original,
            left,
            right,
            meta,
            preprocessed=preprocessed,
        )
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
    status = "取消" if cancelled else "完成"
    print(
        f"[OK] dry-run {status}：采样 {len(sample_results)} 页 → {out_preview_dir}\n"
        f"     对比图: preview_p*_compare.png × {len(compare_images)}\n"
        f"     指标: preview_summary.json"
    )
