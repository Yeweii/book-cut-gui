"""处理流水线：load → deskew → split → crop → binarize → export。

v1.4：合并 PDF 时透传原 PDF 的 outline（书签）+ metadata。
v1.5+ A1：主循环一次 ``convert("L")``，下游全部用 ``*_from_array`` 私有变体，
消除每页 4-5 次重复 RGB→L 转换（133 页省 1.6s）。
v1.5+ B1：主循环直接迭代 ``iter_pages``，不再 ``list`` 物化。
        paper_pages 采样用 ``itertools.islice``。内存 O(N×page) → O(page)。
v1.5+ B2：PDF 输出改 ``save_pdf_bytes`` + ``inject_outline_and_metadata_from_bytes``，
        全内存拼接，去掉 tempfile 磁盘 I/O。
"""

from __future__ import annotations

import argparse
from itertools import chain, islice
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

from book_cut import __version__
from book_cut.io.exporter import (
    ImageFormat,
    inject_outline_and_metadata_from_bytes,
    save_image,
    save_pdf_bytes,
)
from book_cut.io.loader import (
    PageInfo,
    first_pdf_in_folder,
    get_pdf_metadata,
    get_pdf_outline,
    iter_pages,
)
from book_cut.preprocess.binarize import binarize


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


def _crop_pages_from_arrays(sub_arrs: list, mode: str, configs: list | None = None) -> list:
    """v1.5+ A1：对 arr 列表裁切，每张裁成 Image（v1.5+ per-page override）。

    Args:
        sub_arrs: 切分后的子图 ndarray 列表。
        mode: ``trim`` / ``border``。
        configs: 每张子图对应的 ``CropConfig``（可 ``None`` = legacy 默认）。
            ``None`` → 全部子图用同一个 ``config``（向后兼容）。

    说明：per-page override 让每张子图独立决策 config（详见
    ``_resolve_per_page_config``）。本函数只做"按 configs 列表逐张裁切"。
    """

    if configs is None:
        # 向后兼容：所有子图用同一 config
        return _crop_pages_from_arrays_with_config(sub_arrs, mode, None)
    if len(configs) != len(sub_arrs):
        raise ValueError(f"configs 长度 {len(configs)} ≠ sub_arrs 长度 {len(sub_arrs)}")
    out: list = []
    for a, c in zip(sub_arrs, configs, strict=True):
        out.extend(_crop_pages_from_arrays_with_config([a], mode, c))
    return out


def _crop_pages_from_arrays_with_config(
    sub_arrs: list, mode: str, config
) -> list:
    """``_crop_pages_from_arrays`` 的内部单 config helper。"""
    from book_cut.detect.border import crop_to_border_from_array
    from book_cut.detect.trim import _trim_margins_from_array

    if mode == "trim":
        return [_trim_margins_from_array(a, config=config) for a in sub_arrs]
    if mode == "border":
        return [crop_to_border_from_array(a, config=config) for a in sub_arrs]
    raise ValueError(f"未知裁切模式: {mode}")


def _resolve_per_page_config(
    sub_arr: np.ndarray,
    book_config,
    deviation: float,
) -> object | None:
    """v1.5+ per-page override 决策：单张子图用书级还是 per-page config。

    Args:
        sub_arr: 单张子图灰度 ndarray（已切分后）。
        book_config: 书级 CropConfig（``None`` → 走 legacy，不 override）。
        deviation: 偏离阈值（``--paper-deviation``，默认 30）。

    Returns:
        - ``book_config``：不 override（per-paper 接近 book）
        - 新 ``CropConfig``：override 触发（保持 padding/ink_offset，仅换 paper_color）
        - ``None``：legacy 模式（与 book_config=None 对齐）
    """
    if book_config is None:
        return None  # legacy fixed 模式：不 override
    from book_cut.detect.paper import (
        CropConfig,
        estimate_paper_color_from_array,
        should_override,
    )

    per_paper = estimate_paper_color_from_array(sub_arr)
    if not should_override(per_paper, book_config.paper_color, threshold=deviation):
        return book_config  # 偏离 ≤ 阈值：沿用书级

    # override：保持 padding/ink_offset/min_edge_ink，只换 paper_color
    # v1.5+ §5.1：padding 不变（视觉一致性），仅 ink_thr 切到 per-page
    return CropConfig(
        paper_color=per_paper,
        ink_offset=book_config.ink_offset,
        padding=book_config.padding,
        min_edge_ink=book_config.min_edge_ink,
    )


def _build_crop_config(args, sample_pages: list) -> object | None:
    """根据 CLI args 构造 ``CropConfig``（或返 ``None`` 走 legacy 路径）。

    行为表：
    - ``--crop-adaptive fixed`` → 返 ``None``（legacy 阈值 240）
    - ``--crop-adaptive auto`` 且 ``--paper-pages >= 1`` → 用前 N 页估 book paper color
    - ``--crop-adaptive auto`` 且 ``--paper-pages 0/1`` → 每页单独估（每次都算）
    """
    from book_cut.detect.paper import (
        aggregate_paper_color,
        default_crop_config,
        estimate_paper_color,
    )

    crop_adaptive: str = getattr(args, "crop_adaptive", "auto")
    if crop_adaptive == "fixed":
        return None  # legacy 模式：trim/border 走硬编码 threshold=240

    paper_pages: int = max(0, getattr(args, "paper_pages", 5))
    if not sample_pages or paper_pages == 0:
        # 无样页可用：返一个默认 config，每页用 240 (等同 legacy)
        return default_crop_config(paper_color=240.0)

    sampled = sample_pages[:paper_pages]
    colors = [estimate_paper_color(p.image) for p in sampled]
    book_paper = aggregate_paper_color(colors)
    print(
        f"[INFO] 自适应裁切: book paper color = {book_paper:.1f} "
        f"(sampled {len(colors)} pages, raw = {[round(c, 1) for c in colors]})"
    )
    return default_crop_config(paper_color=book_paper)


def _reverse_pair(sub_pages: list) -> list:
    """RTL 模式：1:2 切分时把 [左, 右] 翻成 [右, 左]。

    单页 / 多于 2 页时不动（防御）。
    """
    if len(sub_pages) == 2:
        return [sub_pages[1], sub_pages[0]]
    return sub_pages


def _resolve_outline_source(input_path: Path) -> tuple[Path | None, bool]:
    """决定 outline / metadata 的来源 PDF。

    Returns:
        ``(pdf_path, is_folder_multi)``：
        - 单文件 PDF → ``(path, False)``
        - 文件夹（含 ≥1 个 PDF）→ ``(first_pdf, True)``（多 PDF 时 log 警告）
        - 单图 / 文件夹无 PDF → ``(None, False)``
    """
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return input_path, False
    if input_path.is_dir():
        first = first_pdf_in_folder(input_path)
        if first is None:
            return None, False
        # 判断是不是真的"多 PDF"——>1 才警告
        all_pdfs = sorted(input_path.rglob("*.pdf")) + sorted(
            input_path.rglob("*.PDF")
        )
        return first, len(all_pdfs) > 1
    return None, False


def _write_pdf_with_outline(
    image_paths: list[Path],
    pdf_path: Path,
    toc: list[tuple[int, str, int]],
    metadata: dict[str, str],
    mapping: dict[int, list[int]],
    enabled: bool,
) -> Path:
    """写出最终 PDF（v1.5+ B2：全内存，去 tempfile）。

    - ``enabled`` 且有 ``toc`` / ``metadata`` / ``mapping`` → img2pdf 出 bytes
      → pypdf 从 BytesIO 读 → 注入 outline + metadata → 写 ``pdf_path``
    - 否则 img2pdf bytes → 直接写 ``pdf_path``
    """
    if not (enabled and (toc or metadata) and mapping):
        pdf_bytes = save_pdf_bytes(image_paths)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pdf_bytes)
        return pdf_path

    pdf_bytes = save_pdf_bytes(image_paths)
    # producer 追加 book-cut 标识（透传的同时标记出处）
    meta = dict(metadata)
    if "/Producer" in meta:
        meta["/Producer"] = f"{meta['/Producer']}; book-cut {__version__}"
    else:
        meta["/Producer"] = f"book-cut {__version__}"
    return inject_outline_and_metadata_from_bytes(
        pdf_bytes, pdf_path, toc, meta, mapping
    )


def run_pipeline(args: argparse.Namespace) -> None:
    """根据 CLI args 运行整条流水线（v1.5+ B1：流式）。

    关键：不再 ``list(iter_pages(...))``，主循环直接迭代 generator，
    每页 PageInfo 处理完即被 GC，内存从 O(N×page) → O(page)。
    """
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    fmt: ImageFormat = args.format
    crop_mode: str = getattr(args, "crop", "none")
    binarize_method: str = getattr(args, "binarize", "none")
    deskew_enabled: bool = getattr(args, "deskew", False)
    auto_single_page: bool = getattr(args, "auto_single_page", True)
    page_order: str = getattr(args, "page_order", "ltr")  # v1.4 新增
    outline_enabled: bool = getattr(args, "outline", True)  # v1.4 新增
    book_name = input_path.stem if input_path.is_file() else input_path.name

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

    def _process_one(page: PageInfo, is_sampled_page: bool = False) -> None:
        """处理单页：deskew → split → crop → binarize → save_image.

        v1.5+ per-page override：每张子图独立决定 config（书级 vs per-page）。
        is_sampled_page=True（采样阶段用过的前 N 页）跳过 override，避免自我引用。
        """
        nonlocal counter
        image = page.image

        # 1. 可选：倾斜校正（在切分/裁切之前）
        # v1.5+ A1：走 arr 路径，跳过重复 convert("L")
        if deskew_enabled:
            from book_cut.preprocess.deskew import deskew_from_array

            arr_for_deskew = np.asarray(image.convert("L"))
            arr = deskew_from_array(arr_for_deskew)
        else:
            # v1.5+ A1：主循环唯一一次 RGB→L 转换（uint8，省内存）
            arr = np.asarray(image.convert("L"))

        # 2. 切分（可能产生 1 张单页或 2 张双页）
        offset = getattr(args, "half_offset", 0)
        if args.split == "half":
            from book_cut.split.half import split_half_from_array

            sub_arrs = split_half_from_array(arr, offset=offset)
        else:
            sub_arrs = _split_from_array(arr, args.split, auto_single_page=auto_single_page)

        # v1.4：RTL 模式下，1:2 切分翻成 [右, 左]
        if page_order == "rtl" and len(sub_arrs) == 2:
            sub_arrs = [sub_arrs[1], sub_arrs[0]]

        # 3. 可选：裁切（白边 / 版框内裁）—— arr 路径
        # v1.5+ per-page override：每张子图独立决策 config
        if crop_mode == "none":
            sub_pages = [Image.fromarray(a, mode="L") for a in sub_arrs]
        elif is_sampled_page:
            # 采样页：用书级 config（避免 override 自我引用，proposal §10.2）
            configs = [crop_config] * len(sub_arrs)
            sub_pages = _crop_pages_from_arrays(sub_arrs, crop_mode, configs=configs)
        else:
            # 每张子图独立决策（per-page override）
            per_page_configs = [
                _resolve_per_page_config(a, crop_config, paper_deviation)
                for a in sub_arrs
            ]
            sub_pages = _crop_pages_from_arrays(sub_arrs, crop_mode, configs=per_page_configs)

        # 4. 可选：二值化 —— 公共 API（内部薄包装对 L 模式图无 convert 开销）
        if binarize_method != "none":
            sub_pages = [binarize(p, binarize_method) for p in sub_pages]

        # v1.4：记录原页 → 输出页映射（仅当输入是 outline source PDF 的页）
        if src_pdf_stem is not None and page.source_name == src_pdf_stem:
            outline_mapping[page.page_index] = list(range(counter, counter + len(sub_pages)))

        for p in sub_pages:
            counter += 1
            image_paths.append(save_image(p, output_dir, book_name, counter, fmt=fmt))

    # 采样阶段用了前 paper_pages_n 页（islice chain 顺序保证）。
    # 主循环用 enumerate 区分"采样页"（前 N-1，因为 first_page 已取出）vs 真实页。
    sampled_remaining = paper_pages_n - 1  # 已取 first_page，剩 N-1 个
    _process_one(first_page, is_sampled_page=True)

    # tqdm 包装剩余 iterator（total 不知道 → 不显示 ETA，但有进度计数）
    for i, page in enumerate(tqdm(full_iter, desc="切分", initial=1)):
        _process_one(page, is_sampled_page=(i < sampled_remaining))

    if getattr(args, "pdf", False):
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
