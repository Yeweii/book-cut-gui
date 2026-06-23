"""orchestrator：流水线主循环。

职责：
- ``run_pipeline(args)``：顶层入口（v1.8+ 支持 dry_run）
- ``_process_one(page, ...)``：单页 deskew → split → crop → binarize → save
- ``_split_from_array(arr, strategy, ...)``：split 调度
- ``_crop_pages_from_arrays(...)`` / ``_crop_pages_from_arrays_with_config(...)``：crop 调度
- ``_reverse_pair(sub_pages)``：RTL flip
- ``_compute_split_confidence(...)``：v1.8 split 质量量化（0-1）

v1.6+ C3：从原 455 行 ``pipeline.py`` 拆出，独立模块。
v1.8+ 加 ``dry_run`` / ``sample_n`` / ``preview_dir`` 三个 kwarg；
       ``_process_one`` 加 ``save`` kwarg（False 时返回元数据，不写盘）。
"""

from __future__ import annotations

import argparse
import threading
import time
from itertools import chain, islice
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

from book_cut.io.exporter import ImageFormat, save_image
from book_cut.io.loader import (
    PageInfo,
    get_pdf_metadata,
    get_pdf_outline,
    iter_page_sizes,
    iter_pages,
)
from book_cut.io.page_size import (
    PDF_PAGE_SIZE_CHOICES,
    fit_to_canvas,
    parse_page_size_px,
)
from book_cut.pipeline.crop_config import _build_crop_config, _resolve_per_page_config
from book_cut.pipeline.outline import (
    _resolve_outline_source,
    _write_pdf_with_outline,
)
from book_cut.preprocess.binarize import binarize

# v1.8+ dry-run：per-step 计时开关（避免影响 v1.7 行为；正式版可保持 True）
_TIMING_ENABLED = True


def _split_from_array(arr: np.ndarray, strategy: str, auto_single_page: bool = True) -> list:
    """v1.5+ A1：arr 路径的 splitter 分派。"""
    from book_cut.split.border import split_border_from_array
    from book_cut.split.gutter import split_gutter_from_array
    from book_cut.split.half import split_half_from_array

    if strategy == "half":
        return split_half_from_array(arr)
    if strategy == "gutter":
        return split_gutter_from_array(arr, auto_single_page=auto_single_page)
    if strategy == "border":
        return split_border_from_array(arr)
    raise ValueError(f"未知切分策略: {strategy}")


def _crop_pages_from_arrays(
    sub_arrs: list,
    mode: str,
    configs: list | None = None,
    use_morph: bool = True,
    page_rects: list | None = None,
) -> list:
    """v1.5+ A1：对 arr 列表裁切，每张裁成 Image（v1.5+ per-page override）。

    Args:
        sub_arrs: 切分后的子图 ndarray 列表。
        mode: ``trim`` / ``border``。
        configs: 每张子图对应的 ``CropConfig``（可 ``None`` = legacy 默认）。
            ``None`` → 全部子图用同一个 ``config``（向后兼容）。
        use_morph: v1.6+ B线：trim/border fallback 是否走形态学开运算。
        page_rects: v1.6+ A3 split_border 缓存的每子图版框 rect。
            ``None`` 或 ``[None, ...]`` → crop 自跑 Hough。

    说明：per-page override 让每张子图独立决策 config（详见
    ``_resolve_per_page_config``）。本函数只做"按 configs 列表逐张裁切"。
    """

    if configs is None:
        # 向后兼容：所有子图用同一 config
        return _crop_pages_from_arrays_with_config(
            sub_arrs, mode, None, use_morph=use_morph, page_rects=page_rects
        )
    if len(configs) != len(sub_arrs):
        raise ValueError(f"configs 长度 {len(configs)} ≠ sub_arrs 长度 {len(sub_arrs)}")
    out: list = []
    for i, (a, c) in enumerate(zip(sub_arrs, configs, strict=True)):
        # 每子图对应的 page_rect（v1.6+ A3）
        sub_rects = [page_rects[i]] if page_rects else None
        out.extend(
            _crop_pages_from_arrays_with_config(
                [a], mode, c, use_morph=use_morph, page_rects=sub_rects
            )
        )
    return out


def _crop_pages_from_arrays_with_config(
    sub_arrs: list, mode: str, config, use_morph: bool = True, page_rects: list | None = None
) -> list:
    """``_crop_pages_from_arrays`` 的内部单 config helper。

    v1.6+ 加 ``use_morph`` 参数（B线）+ ``page_rects`` 参数（A3 缓存）。
    """
    from book_cut.detect.border import crop_to_border_from_array
    from book_cut.detect.trim import _trim_margins_from_array

    if mode == "trim":
        return [_trim_margins_from_array(a, config=config, use_morph=use_morph) for a in sub_arrs]
    if mode == "border":
        # v1.6+ A3：page_rects[i] 给 crop 复用 split 阶段的 Hough 结果
        rects = page_rects if page_rects else [None] * len(sub_arrs)
        return [
            crop_to_border_from_array(
                a, config=config, use_morph=use_morph, page_rect=r
            )
            for a, r in zip(sub_arrs, rects, strict=True)
        ]
    raise ValueError(f"未知裁切模式: {mode}")


def _reverse_pair(sub_pages: list) -> list:
    """RTL 模式：1:2 切分时把 [左, 右] 翻成 [右, 左]。

    单页 / 多于 2 页时不动（防御）。
    """
    if len(sub_pages) == 2:
        return [sub_pages[1], sub_pages[0]]
    return sub_pages


# ----------------------------------------------------------------------------
# v1.8+ dry-run 辅助：split confidence 量化
# ----------------------------------------------------------------------------


def _compute_split_confidence(
    arr: np.ndarray,
    strategy: str,
    sub_arrs: list,
    split_x: int | None,
) -> float:
    """split 质量量化（0-1）—— 给 dry-run preview 调参用。

    - gutter: 中心偏离度反向 + 连续白段宽度
    - border: 假设 Hough 找到 4 条线且围成矩形
    - half: 1.0（无检测）
    """
    w = arr.shape[1] if arr.ndim == 2 else arr.shape[1]
    if strategy == "half":
        return 1.0
    if strategy == "gutter" and split_x is not None and len(sub_arrs) == 2:
        center = w / 2.0
        offset_ratio = abs(split_x - center) / center  # 0=正中, 1=最边缘
        if offset_ratio > 0.2:
            return 0.0  # 偏离 > 20% → 极不可信
        # 用子图尺寸比例 + 子图左/右大小差异（理想 1.0）
        left_w = sub_arrs[0].shape[1]
        right_w = sub_arrs[1].shape[1]
        balance = min(left_w, right_w) / max(left_w, right_w)  # 1.0=完美对称
        return round((1.0 - offset_ratio * 5) * balance, 3)
    if strategy == "border" and len(sub_arrs) == 2:
        # border 假定找到了版框，子图尺寸合理（一般 > 200px）
        left_w = sub_arrs[0].shape[1]
        right_w = sub_arrs[1].shape[1]
        if min(left_w, right_w) < 100:
            return 0.3
        balance = min(left_w, right_w) / max(left_w, right_w)
        return round(0.8 * balance, 3)
    return 0.5  # 单页 / 未知情况


def _compute_page(
    page: PageInfo,
    *,
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
    is_sampled_page: bool,
) -> dict:
    """v1.8+ 抽出的纯计算：处理单页但不写盘。

    Returns:
        ``{"original", "sub_pages", "metrics", "page_rects", "sub_arrs", "split_x"}``
    """
    from book_cut.split.border import split_border_with_rects_from_array
    from book_cut.split.gutter import find_gutter_column_from_array
    from book_cut.split.half import split_half_from_array

    image = page.image
    t0 = time.perf_counter() if _TIMING_ENABLED else 0.0

    # 1. deskew
    if deskew_enabled:
        from book_cut.preprocess.deskew import deskew_from_array

        arr_for_deskew = np.asarray(image.convert("L"))
        arr = deskew_from_array(arr_for_deskew)
    else:
        arr = np.asarray(image.convert("L"))
    t_deskew = time.perf_counter() - t0 if _TIMING_ENABLED else 0.0

    # 2. split
    t_split_start = time.perf_counter() if _TIMING_ENABLED else 0.0
    page_rects: list | None = None
    split_x: int | None = None
    if split_strategy == "half":
        sub_arrs = split_half_from_array(arr, offset=half_offset)
    elif split_strategy == "border":
        result = split_border_with_rects_from_array(arr)
        sub_arrs = result.sub_arrays
        page_rects = result.page_rects
    else:
        sub_arrs = _split_from_array(arr, split_strategy, auto_single_page=auto_single_page)
        if split_strategy == "gutter" and len(sub_arrs) == 2:
            split_x = find_gutter_column_from_array(arr)
    t_split = time.perf_counter() - t_split_start if _TIMING_ENABLED else 0.0

    # RTL flip
    if page_order == "rtl" and len(sub_arrs) == 2:
        sub_arrs = [sub_arrs[1], sub_arrs[0]]
        if page_rects is not None:
            page_rects = [page_rects[1], page_rects[0]]

    # 3. crop
    t_crop_start = time.perf_counter() if _TIMING_ENABLED else 0.0
    if crop_mode == "none":
        sub_pages = [Image.fromarray(a, mode="L") for a in sub_arrs]
    elif is_sampled_page:
        configs = [crop_config] * len(sub_arrs)
        sub_pages = _crop_pages_from_arrays(
            sub_arrs, crop_mode, configs=configs, use_morph=use_morph, page_rects=page_rects
        )
    else:
        per_page_configs = [
            _resolve_per_page_config(a, crop_config, paper_deviation) for a in sub_arrs
        ]
        sub_pages = _crop_pages_from_arrays(
            sub_arrs,
            crop_mode,
            configs=per_page_configs,
            use_morph=use_morph,
            page_rects=page_rects,
        )
    t_crop = time.perf_counter() - t_crop_start if _TIMING_ENABLED else 0.0

    # 4. binarize
    t_bin_start = time.perf_counter() if _TIMING_ENABLED else 0.0
    if binarize_method != "none":
        sub_pages = [binarize(p, binarize_method) for p in sub_pages]
    t_bin = time.perf_counter() - t_bin_start if _TIMING_ENABLED else 0.0

    # metrics
    confidence = _compute_split_confidence(arr, split_strategy, sub_arrs, split_x)
    page_metrics = {
        "page_idx": page.page_index,
        "source": page.source_name,
        "size_in": list(image.size),
        "deskew": {
            "applied": deskew_enabled,
            "angle": None,
            "method": "hough" if deskew_enabled else None,
        },
        "split": {
            "method": split_strategy,
            "x": split_x,
            "confidence": confidence,
            "fallback_used": False,
            "fallback_reason": None,
            "size_left": list(sub_pages[0].size) if sub_pages else None,
            "size_right": list(sub_pages[1].size) if len(sub_pages) > 1 else None,
        },
        "crop": {"method": crop_mode, "fallback_used": False},
        "binarize": {
            "method": binarize_method,
            "window": 25 if binarize_method == "sauvola" else None,
            "k": 0.2 if binarize_method == "sauvola" else None,
        },
        "timings_ms": {
            "deskew": round(t_deskew * 1000, 2),
            "split": round(t_split * 1000, 2),
            "crop": round(t_crop * 1000, 2),
            "binarize": round(t_bin * 1000, 2),
        },
        "warnings": [],
    }

    return {
        "original": image,
        "sub_pages": sub_pages,
        "sub_arrs": sub_arrs,
        "page_rects": page_rects,
        "split_x": split_x,
        "metrics": page_metrics,
    }






def run_pipeline(args: argparse.Namespace, cancel_event: threading.Event | None = None) -> None:
    """根据 CLI args 运行整条流水线（v1.5+ B1：流式）。

    关键：不再 ``list(iter_pages(...))``，主循环直接迭代 generator，
    每页 PageInfo 处理完即被 GC，内存从 O(N×page) → O(page)。

    v1.6+ C3：本函数迁到 ``pipeline/orchestrator.py``，outline 与 crop_config
    拆到独立模块，行为完全不变。
    v1.8+：支持 ``dry_run`` 模式（仅跑前 N 页 + 写 preview，不写盘）。
    v1.8.1+：支持 ``cancel_event``（每页边界检查，True 则 break 优雅停止）。
    """
    output_dir = Path(args.output)
    dry_run: bool = bool(getattr(args, "dry_run", False))
    # v1.8+ dry-run：不创建输出目录（避免污染用户文件系统）
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    fmt: ImageFormat = args.format
    crop_mode: str = getattr(args, "crop", "none")
    binarize_method: str = getattr(args, "binarize", "none")
    deskew_enabled: bool = getattr(args, "deskew", False)
    auto_single_page: bool = getattr(args, "auto_single_page", True)
    page_order: str = getattr(args, "page_order", "ltr")  # v1.4 新增
    outline_enabled: bool = getattr(args, "outline", True)  # v1.4 新增
    # v1.6+ B线：--no-morph 关闭形态学（古籍飞白/极小字可见时用）
    use_morph: bool = not getattr(args, "no_morph", False)
    # v1.7 新增：PDF 页面统一尺寸（默认 keep = 保持原图分辨率）
    pdf_page_size: str = getattr(args, "pdf_page_size", "keep")
    book_name = input_path.stem if input_path.is_file() else input_path.name

    # v1.7：决定 (target_w, target_h) —— None 表示 keep（不统一）。
    # 非 PDF 模式 → None（图片输出保持原分辨率）
    target_size: tuple[int, int] | None = None
    if pdf_page_size != "keep":
        if not getattr(args, "pdf", False):
            print(
                f"[WARN] --pdf-page-size={pdf_page_size} 仅在 --pdf 模式生效；"
                "图片输出保持原分辨率"
            )
        else:
            if pdf_page_size in {"a4", "a5", "letter", "legal", "custom"}:
                target_size = parse_page_size_px(
                    pdf_page_size,
                    dim=getattr(args, "pdf_page_dim", None),
                    unit=getattr(args, "pdf_page_unit", "mm"),
                )
            elif pdf_page_size in {"max", "first"}:
                # 先用 iter_page_sizes 流式预扫
                # iter_page_sizes 不会被 islice 消耗（独立于 page_iter）
                # max：所有页中 max(W) × max(H)
                # first：第 1 页的尺寸
                w_max = 0
                h_max = 0
                first_w = first_h = 0
                seen = 0
                for w, h in iter_page_sizes(args.input):
                    if seen == 0:
                        first_w, first_h = w, h
                    if w > w_max:
                        w_max = w
                    if h > h_max:
                        h_max = h
                    seen += 1
                if seen == 0:
                    # 输入无页（防御，与下方"先 peek 第一页"行为一致）
                    pass
                else:
                    if pdf_page_size == "max":
                        target_size = (w_max, h_max)
                        print(f"[INFO] --pdf-page-size max → ({w_max}, {h_max})")
                    else:  # first
                        target_size = (first_w, first_h)
                        print(f"[INFO] --pdf-page-size first → ({first_w}, {first_h})")
            else:
                raise ValueError(
                    f"未知 --pdf-page-size: {pdf_page_size!r}（合法: {PDF_PAGE_SIZE_CHOICES}）"
                )

    # v1.5+ B1：流式 iterator（不再 list 物化整本书）
    page_iter = iter_pages(args.input)

    # paper_pages 采样：从 iterator 头部取前 N 个估 paper color。
    # 注意：islice 会消耗前 N 个 item，所以主循环必须 chain(sampled, remaining)。
    paper_pages_n: int = max(1, getattr(args, "paper_pages", 5))
    sampled_for_paper: list[PageInfo] = list(islice(page_iter, paper_pages_n))
    crop_config = _build_crop_config(args, sampled_for_paper)
    # sampled 在主循环中被 chain 复用，不能 del

    # v1.4：决定 outline / metadata 来源 PDF（仅 PDF 模式下有意义）
    pdf_path_final: Path | None = None
    outline_toc: list[tuple[int, str, int]] = []
    outline_metadata: dict[str, str] = {}
    outline_mapping: dict[int, list[int]] = {}
    src_pdf_stem: str | None = None
    if getattr(args, "pdf", False):
        pdf_path_final = output_dir / f"{book_name}.pdf"
        if outline_enabled:
            src_pdf, is_multi = _resolve_outline_source(input_path)
            if src_pdf is not None:
                try:
                    outline_toc = get_pdf_outline(src_pdf)
                    outline_metadata = get_pdf_metadata(src_pdf)
                except Exception as e:  # noqa: BLE001
                    print(f"[WARN] 读取 PDF metadata/outline 失败: {e}")
                    outline_toc, outline_metadata = [], {}
                if is_multi:
                    print(
                        f"[WARN] 文件夹内含多个 PDF；"
                        f"outline/metadata 仅保留第一个: {src_pdf.name}"
                    )
                if outline_toc:
                    print(f"[INFO] 原 PDF outline: {len(outline_toc)} 个节点")
                src_pdf_stem = src_pdf.stem

    # v1.5+ B1：先 peek 第一页验证非空，再进入主循环（保持原有"WARN: 0 页"行为）
    # sampled_for_paper + page_iter 拼成完整流（避免 islice 消耗导致主循环丢页）
    full_iter = chain(sampled_for_paper, page_iter)
    try:
        first_page = next(full_iter)
    except StopIteration:
        print(f"[WARN] 输入未发现任何页: {args.input}")
        return

    image_paths: list[Path] = []
    counter = 0

    # v1.5+ per-page override：偏离阈值（CLI --paper-deviation，默认 30）
    paper_deviation: float = float(getattr(args, "paper_deviation", 30))

    # v1.8+ dry-run：采样数 / 预览输出目录（dry_run 已在函数顶部定义）
    sample_n: int = max(1, int(getattr(args, "sample_n", 3)))
    preview_dir: Path | None = (
        Path(args.preview_output) if getattr(args, "preview_output", None) else None
    )

    # 公共单页处理（v1.8+ 拆出）：用纯计算函数 + 不同的"保存策略"
    def _save_subpages(sub_pages: list, page: PageInfo) -> None:
        """把 sub_pages 写盘（v1.7 fit-to-target + v1.4 outline 映射 + v1.8 dry-run skip）。"""
        nonlocal counter
        # v1.4：记录原页 → 输出页映射（仅当输入是 outline source PDF 的页）
        if src_pdf_stem is not None and page.source_name == src_pdf_stem:
            outline_mapping[page.page_index] = list(range(counter, counter + len(sub_pages)))
        for p in sub_pages:
            counter += 1
            # v1.7：fit-to-target（target_size is None → keep 原图）
            if target_size is not None and p.size != target_size:
                p = fit_to_canvas(p, target_size[0], target_size[1])
            image_paths.append(save_image(p, output_dir, book_name, counter, fmt=fmt))

    # 采样阶段用了前 paper_pages_n 页（islice chain 顺序保证）。
    sampled_remaining = paper_pages_n - 1  # 已取 first_page，剩 N-1 个

    if dry_run:
        # v1.8+ dry-run 模式：仅跑前 sample_n 页 + 渲染预览，不写盘、不生成 PDF
        from book_cut.pipeline.dry_run import run_dry_run as _dry_run

        _dry_run(
            first_page=first_page,
            full_iter=full_iter,
            sampled_remaining=sampled_remaining,
            sample_n=sample_n,
            preview_dir=preview_dir,
            input_path=input_path,
            deskew_enabled=deskew_enabled,
            auto_single_page=auto_single_page,
            page_order=page_order,
            crop_mode=crop_mode,
            binarize_method=binarize_method,
            crop_config=crop_config,
            paper_deviation=paper_deviation,
            split_strategy=args.split,
            half_offset=getattr(args, "half_offset", 0),
            use_morph=use_morph,
            cancel_event=cancel_event,
        )
        return  # dry-run 提前退出：不写 image_paths，不生成 PDF

    # 正常模式：每页 compute + save
    first_result = _compute_page(
        first_page,
        deskew_enabled=deskew_enabled,
        auto_single_page=auto_single_page,
        page_order=page_order,
        crop_mode=crop_mode,
        binarize_method=binarize_method,
        crop_config=crop_config,
        paper_deviation=paper_deviation,
        split_strategy=args.split,
        half_offset=getattr(args, "half_offset", 0),
        use_morph=use_morph,
        is_sampled_page=True,
    )
    _save_subpages(first_result["sub_pages"], first_page)

    # v1.8.1+ cancel：在每页边界检查（单页计算是原子的，不可中断）
    cancelled = False
    for i, page in enumerate(tqdm(full_iter, desc="切分", initial=1)):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            print(f"[INFO] 用户取消：已处理 {counter} 张图（在第 {i + 1} 页边界停止）")
            break
        result = _compute_page(
            page,
            deskew_enabled=deskew_enabled,
            auto_single_page=auto_single_page,
            page_order=page_order,
            crop_mode=crop_mode,
            binarize_method=binarize_method,
            crop_config=crop_config,
            paper_deviation=paper_deviation,
            split_strategy=args.split,
            half_offset=getattr(args, "half_offset", 0),
            use_morph=use_morph,
            is_sampled_page=(i < sampled_remaining),
        )
        _save_subpages(result["sub_pages"], page)

    # 取消时不写 PDF（避免半截输出）
    if getattr(args, "pdf", False) and not cancelled:
        assert pdf_path_final is not None
        _write_pdf_with_outline(
            image_paths=image_paths,
            pdf_path=pdf_path_final,
            toc=outline_toc,
            metadata=outline_metadata,
            mapping=outline_mapping,
            enabled=outline_enabled,
        )
        print(f"[OK] PDF: {pdf_path_final}")

    print(f"[OK] 输出 {len(image_paths)} 张图片至 {output_dir}")
