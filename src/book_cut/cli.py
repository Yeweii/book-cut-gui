"""CLI 入口。"""

from __future__ import annotations

import argparse
import os

from book_cut.io.page_size import (
    PDF_PAGE_SIZE_CHOICES,
    PDF_PAGE_UNIT_CHOICES,
)
from book_cut.preprocess.binarize import BINARIZE_CLEANUP_CHOICES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="book-cut",
        description="古籍双页切分工具（PDF/图片 → 单页图 + 可选 PDF）",
    )
    parser.add_argument("--input", "-i", help="输入路径：PDF / 图片 / 文件夹")
    parser.add_argument("--output", "-o", help="输出目录")
    parser.add_argument(
        "--clean-output",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="v2.3.5+：运行前先 ``rmtree(--output)``（避免新旧文件混在一起）。"
        "默认 False（不删）。**有数据丢失风险**，建议先备份。",
    )
    parser.add_argument(
        "--deskew",
        action="store_true",
        help="倾斜校正（Hough 法，auto 回退投影法）",
    )
    parser.add_argument(
        "--split",
        choices=["none", "half", "gutter", "border", "manual"],
        default="gutter",
        help="切分策略：none=不切分（输入已是单页，直接走 crop）/"
        "half=对半（**要求扫描严格居中**；不确定时请用 gutter） / "
        "gutter=中缝（默认）/ border=版框线 / "
        "manual=手动（v2.4+ 配合 --manual-split-x 或 --manual-split-preset，整本书一条线）",
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
        choices=["none", "trim", "border", "manual"],
        default="none",
        help="单页裁切：none=不裁 / trim=切白边 / border=版框内裁 / manual=手动裁切（v2.2+，配合 --manual-*）",
    )
    parser.add_argument(
        "--crop-adaptive",
        choices=["auto", "fixed"],
        default="auto",
        help="裁切阈值/边距策略：auto=按纸张色自适应（默认）/ fixed=v1.1 硬编码 240",
    )
    # v2.2+：manual crop（用户给 4 个 padding；auto 完全跳过）
    parser.add_argument(
        "--manual-odd-padding",
        type=str,
        default=None,
        help="手动裁切 padding（v2.2+）。奇页 4 个 padding："
        "顺序或 K=V 两种格式，如 '50,40,80,30'（T,B,I,O）或 'T=50,B=40,I=80,O=30'。"
        "T=顶, B=底, I=中缝侧, O=外侧。"
        "需配合 --crop manual 生效。",
    )
    parser.add_argument(
        "--manual-mirror-even",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="偶页是否自动 inner↔outer 镜像（v2.2+；默认 True）。"
        "古籍双页扫描 odd/even 物理镜像，关掉则偶页也用同样 I/O。"
        "split=none 时此参数无效（无奇偶之分）。"
        "需配合 --crop manual 生效。",
    )
    parser.add_argument(
        "--manual-preset",
        type=str,
        default=None,
        help="从 JSON preset 文件加载 manual profile（v2.2+）。"
        "格式见 samples/crop_profiles/*.json。"
        "若同时给 --manual-odd-padding，preset 优先。"
        "需配合 --crop manual 生效。",
    )
    parser.add_argument(
        "--manual-save-preset",
        type=str,
        default=None,
        help="将当前 manual 配置（--manual-odd-padding 等）保存为 JSON preset（v2.2+）。"
        "便于跨书复用。需配合 --crop manual 生效。",
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
    # v2.1+：trim A 方案 —— 二值化 trim source
    parser.add_argument(
        "--trim-source",
        choices=["gray", "binarized"],
        default="gray",
        help="trim 的 ink mask 来源（v2.1+）："
        "gray=灰度阈值（默认，行为不变）/"
        "binarized=走 otsu 二值化拿 mask（抗 paper color 估计偏差 / 暗角）。"
        "需配合 --crop trim 生效。",
    )
    # v2.1+：trim B 方案 —— CCA 主体过滤
    parser.add_argument(
        "--trim-min-component-ratio",
        type=float,
        default=0.0,
        help="trim CCA 主体过滤阈值（v2.1+）。"
        "0=关闭（默认，行为不变）；>0=启用，"
        "滤除 area < ratio × 总像素 的小噪点 和 aspect > 10 的狭长版框线。"
        "建议 0.0001~0.001；过大（如 0.5）→ fallback 原 mask。"
        "需配合 --crop trim 生效。",
    )
    # v2.1+：trim C 方案 —— 在 adaptive padding 之上叠加额外 padding
    parser.add_argument(
        "--trim-padding",
        type=int,
        default=0,
        help="trim 在 adaptive padding 之上额外叠加的像素数（v2.1+；默认 0）。"
        "适用于 --trim-min-component-ratio > 0 时，版框/版心标记被 mask 滤掉，"
        "默认 30px padding 不足以让版心标记（鱼尾/边栏）远离输出边。"
        "建议 30~60；过大会损失更多画面。"
        "需配合 --crop trim 生效。",
    )
    # v2.1+：trim D 方案 —— 版心保护区
    parser.add_argument(
        "--trim-gutter-band",
        type=str,
        default=None,
        help="trim 版心保护区 (v2.1+)，格式 'L,R'（如 '0.35,0.5'），"
        "其中 L/R 为版心带左右边界占图像宽度的比例。"
        "在版心带内的连通区豁免 CCA aspect 过滤（保留鱼尾/版心装饰），"
        "但仍受 min_area 阈值约束（仅滤 1-3 px 单像素噪点）。"
        "需配合 --trim-min-component-ratio > 0 生效。"
        "古籍版心参考：未分割图像（中部）='0.4,0.6'；"
        "分割后左页（鱼尾在右）='0.7,1.0'；右页（鱼尾在左）='0.0,0.3'。"
        "多 band 场景请用 --trim-gutter-bands（可与本参数共存合并）。",
    )
    # v2.1+ G 方案：trim 多 band 豁免（双页扫描右侧副页保留）
    parser.add_argument(
        "--trim-gutter-bands",
        type=str,
        default=None,
        help="trim 多版心保护区 (v2.1+)，格式 'L1,R1,L2,R2,...'（如 '0.4,0.5,0.7,0.9'）。"
        "连通区 bbox 中心列落在**任一**带内即豁免 CCA aspect 过滤。"
        "适用于双页扫描 + --split none：同时保留中央版心 + 右侧副页区。"
        "需配合 --trim-min-component-ratio > 0 生效。"
        "与 --trim-gutter-band 共存时合并为统一 band 列表。",
    )
    # v2.1+ B 方案：trim strict 后置过滤（排除页眉/页脚稀疏行）
    parser.add_argument(
        "--trim-strict",
        action="store_true",
        default=False,
        help="trim 后置过滤 (v2.1+)：排除稀疏行（页眉/页脚）。"
        "算法：row ink 阈值 = max(50, max_row_ink × 0.1)，"
        "低于阈值的行不进 bbox。"
        "适用于古籍双页扫描：trim 主体过滤后保留的页眉/页脚小字会被排除。"
        "需配合 --crop trim + --trim-source binarized 生效。",
    )
    # v2.1+：adaptive padding 覆盖
    parser.add_argument(
        "--adaptive-padding",
        type=int,
        default=None,
        help="trim 输出保留的最小边距像素数（v2.1+；覆盖 adaptive 公式）。"
        "默认 None = min(5, min(h,w)*0.02)（v1.9 行为，cap 30）。"
        "设值后 = N 像素（opt-in），用于微调输出松紧度："
        "设 0=完全贴 mask bbox（最紧）；"
        "设 30~60=加保护边（防止鱼尾/边栏贴边）。"
        "需配合 --crop-adaptive auto 生效（fixed 路径不生效）。",
    )
    # v2.1+ E2：trim 版框检测（古籍版框页专用）
    parser.add_argument(
        "--trim-frame",
        action="store_true",
        default=False,
        help="trim 版框检测（v2.1+ E2）：用 CCA 找最大空心矩形作为裁切边界，"
        "解决古籍扫描零散噪点导致 trim 留过多白边的问题。"
        "检测失败 fallback 到原 ink bbox。",
    )
    parser.add_argument(
        "--trim-frame-min-ratio",
        type=float,
        default=0.30,
        help="trim 版框 bbox 占图像面积的最小比例（默认 0.30）。"
        "太小（如页眉小框）会被滤掉。",
    )
    parser.add_argument(
        "--trim-frame-max-fill",
        type=float,
        default=0.15,
        help="trim 版框 bbox 填充率上限（默认 0.15，空心判定）。"
        "实心块（fill=1.0）会被滤掉，只留空心框。",
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
    # v2.3.3+：二值化后清理（古籍扫描件去除尘点 / 飞墨）
    parser.add_argument(
        "--binarize-cleanup",
        choices=BINARIZE_CLEANUP_CHOICES,
        default="components",
        help="二值化后清理策略（v2.3.3+；默认 components）："
        "none=不清理 / morph=3×3 形态学开运算（去 specks，1px 笔画变细）/"
        "components=丢 < 4 px² 黑簇（推荐，最安全）/ both=morph + components",
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
        default="rtl",
        help="1:2 切分时输出顺序：ltr=先左后右 / rtl=先右后左（v2.4+ 默认；古籍竖排常用）",
    )
    # v2.4+：manual split 三件套
    parser.add_argument(
        "--manual-split-x",
        type=int,
        default=None,
        help="手动切分线 x 坐标（v2.4+；post-deskew 坐标系下，1 ≤ x < W）。"
        "需配合 --split manual 使用。与 --manual-split-preset 同时给时，preset 优先。",
    )
    parser.add_argument(
        "--manual-split-preset",
        type=str,
        default=None,
        help="手动切分线 JSON preset 路径（v2.4+；v1 schema，参见 samples/crop_profiles/v2_manual_split_example.json）。"
        "需配合 --split manual 使用。preset 含 deskew_applied 字段，与 --deskew 状态不一致时 fatal (MS009)。",
    )
    parser.add_argument(
        "--pick-split-line",
        action="store_true",
        help="v2.4+ 子命令：弹 GUI 选切分线，写入 JSON 到 -o/--output。"
        "用法：python -m book_cut --pick-split-line -i book.pdf -o preset.json",
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

    if args.pick_split_line:
        if not args.input or not args.output:
            parser.error("--pick-split-line 需要 -i INPUT 与 -o OUTPUT_JSON")
        from book_cut.gui import run_pick_split_line
        return run_pick_split_line(args)

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
