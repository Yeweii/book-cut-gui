"""CLI 入口。"""

from __future__ import annotations

import argparse
import os

from book_cut.io.page_size import (
    PDF_PAGE_SIZE_CHOICES,
    PDF_PAGE_UNIT_CHOICES,
)


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
        choices=["none", "half", "gutter", "border"],
        default="gutter",
        help="切分策略：none=不切分（输入已是单页，直接走 crop）/"
        "half=对半（**要求扫描严格居中**；不确定时请用 gutter） / "
        "gutter=中缝（默认）/ border=版框线",
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
        "--paper-deviation",
        type=int,
        default=30,
        help="per-page paper color override 触发阈值（仅 --crop-adaptive auto 时生效；默认 30）。"
        "某子图 p95 偏离书级超过此值时，单页改用 per-page paper color（只换 ink_thr，padding 不变）。"
        "0=全 per-page；999=永不 override（等同 v1.3 行为）。",
    )
    parser.add_argument(
        "--no-morph",
        action="store_true",
        help="关闭 trim 阶段的形态学开运算（v1.6+）。古籍飞白 / 6pt 注疏等极小字"
        "（1-2 px 笔画）会被形态学当尘点吃掉；遇到此场景用 --no-morph 保留。"
        "默认开（抗 1-3 px 尘点 / 折痕）。",
    )
    # v1.9：图片预处理增强
    parser.add_argument(
        "--preprocess",
        type=str,
        default="",
        help="图像预处理链（v1.9+；deskew 之前应用）："
        "逗号分隔 op，可选 '=value' 覆盖默认参数。"
        "可用 op：sharpen / denoise / clahe / gamma。"
        "示例：--preprocess 'denoise=7,clahe=2.0,sharpen=1.5'"
        "或 --preprocess 'gamma=1.3'（深底封面）。"
        "默认空（不处理；保持 v1.8 行为）。",
    )
    parser.add_argument(
        "--preprocess-quality",
        choices=["fast", "balanced", "best"],
        default="balanced",
        help="预处理质量档（v1.9+；默认 balanced）："
        "fast=PIL 内置（零 OpenCV 调用）/ balanced=cv2 默认参数 / best=cv2 高质量参数。"
        "可被环境变量 BOOKCUT_PREPROCESS_QUALITY 覆盖。",
    )
    parser.add_argument(
        "--binarize",
        choices=["none", "otsu", "adaptive", "sauvola"],
        default="none",
        help="二值化算法（默认 none；古籍推荐 sauvola）",
    )
    # v2.0+：二值化输出模式（默认 1bit，体积 8x 缩减；8bit = v1.9 行为）
    _binary_mode_default = os.environ.get("BOOKCUT_BINARY_MODE", "1bit")
    if _binary_mode_default not in ("1bit", "8bit"):
        _binary_mode_default = "1bit"
    parser.add_argument(
        "--binary-mode",
        choices=["1bit", "8bit"],
        default=_binary_mode_default,
        help="二值化输出位深（v2.0+；默认 1bit）："
        "1bit=1-bit 调色板（PNG/PDF 体积缩到 1/8，推荐） / "
        "8bit=8-bit 灰度（v1.9 行为，向后兼容）。"
        "可被环境变量 BOOKCUT_BINARY_MODE 覆盖。",
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
    # v1.7：PDF 页面统一尺寸
    parser.add_argument(
        "--pdf-page-size",
        choices=PDF_PAGE_SIZE_CHOICES,
        default="keep",
        help="PDF 页面统一尺寸（v1.7+；仅 --pdf 模式生效）："
        "keep=保持原图分辨率（默认）/ max=所有页 max(W)×max(H) / "
        "first=首页尺寸 / a4 / a5 / letter / legal / custom=配合 --pdf-page-dim+--pdf-page-unit",
    )
    parser.add_argument(
        "--pdf-page-dim",
        default=None,
        help='PDF 页面自定义尺寸 "WxH"（如 280x200；仅 --pdf-page-size custom 时生效）',
    )
    parser.add_argument(
        "--pdf-page-unit",
        choices=PDF_PAGE_UNIT_CHOICES,
        default="mm",
        help="自定义尺寸单位（仅 --pdf-page-size custom 时生效；默认 mm）",
    )
    parser.add_argument(
        "--format",
        choices=["png", "jpg", "jpeg", "tif", "tiff", "webp"],
        default="png",
        help="输出图片格式（默认 png）",
    )
    # v1.8+ dry-run 预览模式
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式（v1.8+）：不写实际输出，仅跑前 N 页出对比图 + 指标 JSON。"
        "--pdf / --format / --pdf-page-size / --no-outline 等写盘 flag 全部 warn 后忽略。",
    )
    parser.add_argument(
        "--sample-n",
        type=int,
        default=3,
        help="dry-run 采样页数（仅 --dry-run 生效；默认 3；最小 1）",
    )
    parser.add_argument(
        "--preview-output",
        default=None,
        help="dry-run 预览输出目录（仅 --dry-run 生效；默认系统 tmpdir 带时间戳）",
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

    # v1.8+ dry-run 校验
    if args.dry_run:
        if args.sample_n < 1:
            parser.error("--sample-n 必须 >= 1")
        # 写盘相关 flag 全部 warn 后忽略
        if args.pdf:
            print("[WARN] --dry-run 模式忽略 --pdf")
        if args.pdf_page_size != "keep":
            print(f"[WARN] --dry-run 模式忽略 --pdf-page-size={args.pdf_page_size}")
        if not args.outline:
            print("[WARN] --dry-run 模式忽略 --no-outline")
    else:
        if args.sample_n != 3:
            print(f"[WARN] --sample-n={args.sample_n} 仅在 --dry-run 生效；忽略")
        if args.preview_output:
            print("[WARN] --preview-output 仅在 --dry-run 生效；忽略")

    from book_cut.pipeline import run_pipeline

    run_pipeline(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
