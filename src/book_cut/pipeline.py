"""处理流水线：load → deskew → split → crop → binarize → export。

v1.4：合并 PDF 时透传原 PDF 的 outline（书签）+ metadata。
v1.5+ A1：主循环一次 ``convert("L")``，下游全部用 ``*_from_array`` 私有变体，
消除每页 4-5 次重复 RGB→L 转换（133 页省 1.6s）。
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image
from tqdm import tqdm

from book_cut import __version__
from book_cut.io.exporter import ImageFormat, inject_outline_and_metadata, save_image, save_pdf
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


def _crop_pages_from_arrays(sub_arrs: list, mode: str, config=None) -> list:
    """v1.5+ A1：对 arr 列表裁切，每张裁成 Image。"""
    from book_cut.detect.border import crop_to_border_from_array
    from book_cut.detect.trim import _trim_margins_from_array

    if mode == "trim":
        return [_trim_margins_from_array(a, config=config) for a in sub_arrs]
    if mode == "border":
        return [crop_to_border_from_array(a, config=config) for a in sub_arrs]
    raise ValueError(f"未知裁切模式: {mode}")


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
    """写出最终 PDF。

    - ``enabled`` 且有 ``toc`` / ``metadata`` / ``mapping`` → img2pdf 出中间 PDF
      → pypdf 注入 outline + metadata → 覆盖
    - 否则直接 img2pdf 写 ``pdf_path``
    """
    if not (enabled and (toc or metadata) and mapping):
        return save_pdf(image_paths, pdf_path)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        save_pdf(image_paths, tmp_path)
        # producer 追加 book-cut 标识（透传的同时标记出处）
        meta = dict(metadata)
        if "/Producer" in meta:
            meta["/Producer"] = f"{meta['/Producer']}; book-cut {__version__}"
        else:
            meta["/Producer"] = f"book-cut {__version__}"
        return inject_outline_and_metadata(tmp_path, pdf_path, toc, meta, mapping)
    finally:
        tmp_path.unlink(missing_ok=True)


def run_pipeline(args: argparse.Namespace) -> None:
    """根据 CLI args 运行整条流水线。"""
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    pages: list[PageInfo] = list(iter_pages(args.input))
    if not pages:
        print(f"[WARN] 输入未发现任何页: {args.input}")
        return

    fmt: ImageFormat = args.format
    crop_mode: str = getattr(args, "crop", "none")
    binarize_method: str = getattr(args, "binarize", "none")
    deskew_enabled: bool = getattr(args, "deskew", False)
    auto_single_page: bool = getattr(args, "auto_single_page", True)
    page_order: str = getattr(args, "page_order", "ltr")  # v1.4 新增
    outline_enabled: bool = getattr(args, "outline", True)  # v1.4 新增
    book_name = input_path.stem if input_path.is_file() else input_path.name

    # 自适应裁切：先估 book paper color，再注入到 crop step
    paper_pages_n: int = max(1, getattr(args, "paper_pages", 5))
    crop_config = _build_crop_config(args, pages[:paper_pages_n])

    # v1.4：决定 outline / metadata 来源 PDF（仅 PDF 模式下有意义）
    pdf_path_final: Path | None = None
    outline_toc: list[tuple[int, str, int]] = []
    outline_metadata: dict[str, str] = {}
    outline_mapping: dict[int, list[int]] = {}
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
            # src_pdf 是 outline source；mapping 只为它构建
            # 保存供循环内用
        # 没开 outline 或 src_pdf is None：mapping 留空 → _write_pdf_with_outline 走纯 img2pdf

    image_paths: list[Path] = []
    counter = 0
    src_pdf_stem: str | None = (
        _resolve_outline_source(input_path)[0].stem
        if (pdf_path_final is not None and outline_enabled and _resolve_outline_source(input_path)[0] is not None)
        else None
    )
    for page in tqdm(pages, desc="切分"):
        image = page.image

        # 1. 可选：倾斜校正（在切分/裁切之前）
        # v1.5+ A1：走 arr 路径，跳过重复 convert("L")
        if deskew_enabled:
            from book_cut.preprocess.deskew import deskew_from_array

            # deskew 自己也转一次（用 arr 路径省一次 _to_gray_array 调用）
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
        if crop_mode == "none":
            sub_pages = [Image.fromarray(a, mode="L") for a in sub_arrs]
        else:
            sub_pages = _crop_pages_from_arrays(sub_arrs, crop_mode, config=crop_config)

        # 4. 可选：二值化 —— 公共 API（内部薄包装对 L 模式图无 convert 开销）
        if binarize_method != "none":
            sub_pages = [binarize(p, binarize_method) for p in sub_pages]

        # v1.4：记录原页 → 输出页映射（仅当输入是 outline source PDF 的页）
        if src_pdf_stem is not None and page.source_name == src_pdf_stem:
            outline_mapping[page.page_index] = list(range(counter, counter + len(sub_pages)))

        for p in sub_pages:
            counter += 1
            image_paths.append(save_image(p, output_dir, book_name, counter, fmt=fmt))

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
