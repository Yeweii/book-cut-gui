"""CLI 入口。"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-cut",
        description="古籍双页切分工具（PDF/图片 → 单页图 + 可选 PDF）",
    )
    parser.add_argument("--input", "-i", help="输入路径：PDF / 图片 / 文件夹")
    parser.add_argument("--output", "-o", help="输出目录")
    parser.add_argument(
        "--deskew",
        action="store_true",
        help="倾斜校正（Hough 法，auto 回退投影法）",
    )
    parser.add_argument(
        "--split",
        choices=["half", "gutter", "border"],
        default="gutter",
        help="切分策略：half=对半 / gutter=中缝（默认）/ border=版框线",
    )
    parser.add_argument(
        "--no-single-page",
        dest="auto_single_page",
        action="store_false",
        help="关闭单页自动检测（强制对半切）",
    )
    parser.add_argument(
        "--half-offset",
        type=int,
        default=0,
        help="对半切像素偏移（仅 --split half 生效）",
    )
    parser.add_argument(
        "--crop",
        choices=["none", "trim", "border"],
        default="none",
        help="单页裁切：none=不裁 / trim=切白边 / border=版框内裁",
    )
    parser.add_argument(
        "--crop-adaptive",
        choices=["auto", "fixed"],
        default="auto",
        help="裁切阈值/边距策略：auto=按纸张色自适应（默认）/ fixed=v1.1 硬编码 240",
    )
    parser.add_argument(
        "--paper-pages",
        type=int,
        default=5,
        help="用于学习书级纸张色的采样页数（仅 --crop-adaptive auto 时生效；默认 5）",
    )
    parser.add_argument(
        "--binarize",
        choices=["none", "otsu", "adaptive", "sauvola"],
        default="none",
        help="二值化算法（默认 none；古籍推荐 sauvola）",
    )
    parser.add_argument("--pdf", action="store_true", help="同时输出合并 PDF（img2pdf 无损）")
    parser.add_argument(
        "--page-order",
        choices=["ltr", "rtl"],
        default="ltr",
        help="1:2 切分时输出顺序：ltr=先左后右（默认）/ rtl=先右后左（古籍竖排常用）",
    )
    parser.add_argument(
        "--no-outline",
        dest="outline",
        action="store_false",
        default=True,
        help="关闭 PDF outline（书签）/ metadata 透传（仅 --pdf 模式有效；兜底用）",
    )
    parser.add_argument(
        "--format",
        choices=["png", "jpg", "jpeg", "tif", "tiff", "webp"],
        default="png",
        help="输出图片格式（默认 png）",
    )
    parser.add_argument("--gui", action="store_true", help="启动 GUI")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from book_cut.gui import run_gui

        run_gui()
        return 0

    if not args.input or not args.output:
        parser.error("--input 与 --output 必填（或使用 --gui）")

    from book_cut.pipeline import run_pipeline

    run_pipeline(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
