"""处理流水线：load → deskew → split → crop → binarize → export。"""

from __future__ import annotations

import argparse
from pathlib import Path

from tqdm import tqdm

from book_cut.io.exporter import ImageFormat, save_image, save_pdf
from book_cut.io.loader import PageInfo, iter_pages
from book_cut.preprocess.binarize import binarize
from book_cut.split.border import split_border
from book_cut.split.gutter import split_gutter
from book_cut.split.half import split_half

SPLITTERS = {
    "half": split_half,
    "gutter": split_gutter,
    "border": split_border,
}


def _split(image, strategy: str, auto_single_page: bool = True) -> list:
    splitter = SPLITTERS[strategy]
    if strategy == "gutter":
        return splitter(image, auto_single_page=auto_single_page)
    return splitter(image)


def _crop_pages(pages: list, mode: str, config=None) -> list:
    """对切分后的每页分别裁切。

    Args:
        pages: 已切分的 PIL Image 列表。
        mode: ``"trim"`` / ``"border"``。
        config: ``CropConfig`` 或 ``None``（legacy 模式）。
    """
    from book_cut.detect.border import crop_to_border
    from book_cut.detect.trim import trim_margins

    if mode == "trim":
        return [trim_margins(p, config=config) for p in pages]
    if mode == "border":
        return [crop_to_border(p, config=config) for p in pages]
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


def run_pipeline(args: argparse.Namespace) -> None:
    """根据 CLI args 运行整条流水线。"""
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    pages: list[PageInfo] = list(iter_pages(args.input))
    if not pages:
        print(f"[WARN] 输入未发现任何页: {args.input}")
        return

    fmt: ImageFormat = args.format
    crop_mode: str = getattr(args, "crop", "none")
    binarize_method: str = getattr(args, "binarize", "none")
    deskew_enabled: bool = getattr(args, "deskew", False)
    auto_single_page: bool = getattr(args, "auto_single_page", True)
    book_name = Path(args.input).stem if Path(args.input).is_file() else Path(args.input).name

    # 自适应裁切：先估 book paper color，再注入到 crop step
    paper_pages_n: int = max(1, getattr(args, "paper_pages", 5))
    crop_config = _build_crop_config(args, pages[:paper_pages_n])

    image_paths: list[Path] = []
    counter = 0
    for page in tqdm(pages, desc="切分"):
        image = page.image

        # 1. 可选：倾斜校正（在切分/裁切之前）
        if deskew_enabled:
            from book_cut.preprocess.deskew import deskew as do_deskew

            image = do_deskew(image)

        # 2. 切分（可能产生 1 张单页或 2 张双页）
        if args.split == "half":
            offset = getattr(args, "half_offset", 0)
            sub_pages = split_half(image, offset=offset)
        else:
            sub_pages = _split(image, args.split, auto_single_page=auto_single_page)

        # 3. 可选：裁切（白边 / 版框内裁）
        if crop_mode != "none":
            sub_pages = _crop_pages(sub_pages, crop_mode, config=crop_config)

        # 4. 可选：二值化
        if binarize_method != "none":
            sub_pages = [binarize(p, binarize_method) for p in sub_pages]

        for p in sub_pages:
            counter += 1
            image_paths.append(save_image(p, output_dir, book_name, counter, fmt=fmt))

    if getattr(args, "pdf", False):
        pdf_path = output_dir / f"{book_name}.pdf"
        save_pdf(image_paths, pdf_path)
        print(f"[OK] PDF: {pdf_path}")

    print(f"[OK] 输出 {len(image_paths)} 张图片至 {output_dir}")
