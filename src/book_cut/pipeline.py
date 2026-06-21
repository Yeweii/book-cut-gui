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


def _crop_pages(pages: list, mode: str) -> list:
    """对切分后的每页分别裁切。"""
    from book_cut.detect.border import crop_to_border
    from book_cut.detect.trim import trim_margins

    if mode == "trim":
        return [trim_margins(p) for p in pages]
    if mode == "border":
        return [crop_to_border(p) for p in pages]
    raise ValueError(f"未知裁切模式: {mode}")


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
            sub_pages = _crop_pages(sub_pages, crop_mode)

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
