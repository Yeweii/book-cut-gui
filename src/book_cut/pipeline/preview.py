"""v1.8 dry-run 预览输出：对比拼图 + 指标 JSON。

负责：
- ``render_compare``：3 列（原图 / L / R）并排拼图 + 标题 + split line
- ``write_preview``：把采样结果写到 ``preview_dir``
- ``compute_summary``：汇总 JSON（每页 metrics + 调参提示）

设计：所有函数都是**纯函数 + 接受简单参数**，不依赖 argparse.Namespace，
方便单测与外部复用。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# 单列目标高度（px）；超过 6000px 总宽时按比例缩
DEFAULT_TARGET_HEIGHT = 800
MAX_TOTAL_WIDTH = 6000
TITLE_HEIGHT = 60
COLUMN_PADDING = 16
SPLIT_LINE_COLOR = (220, 50, 50)  # 红色虚线


def _resize_to_height(img: Image.Image, target_h: int) -> Image.Image:
    """等比缩放到目标高度。"""
    w, h = img.size
    if h == target_h:
        return img
    scale = target_h / h
    new_w = max(1, int(round(w * scale)))
    return img.resize((new_w, target_h), Image.Resampling.LANCZOS)


def _fit_columns(images: list[Image.Image], target_h: int) -> list[Image.Image]:
    """把多张子图统一到 target_h 高度；总宽超 MAX_TOTAL_WIDTH 时按比例缩。"""
    if not images:
        return []
    resized = [_resize_to_height(img, target_h) for img in images]
    total_w = sum(img.size[0] for img in resized) + COLUMN_PADDING * (len(resized) + 1)
    if total_w > MAX_TOTAL_WIDTH:
        scale = MAX_TOTAL_WIDTH / total_w
        new_h = max(64, int(round(target_h * scale)))
        resized = [_resize_to_height(img, new_h) for img in resized]
    return resized


def _label(text: str, size: int = 16) -> Image.Image:
    """渲染一行文字为 RGB 图像（透明背景 → 白底）。"""
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0] + 8
    h = bbox[3] - bbox[1] + 8
    img = Image.new("RGB", (max(w, 64), max(h, 20)), "white")
    draw = ImageDraw.Draw(img)
    draw.text((4, 4 - bbox[1]), text, fill="black", font=font)
    return img


def render_compare(
    original: Image.Image,
    left: Image.Image | None,
    right: Image.Image | None,
    meta: dict,
    target_height: int = DEFAULT_TARGET_HEIGHT,
    preprocessed: Image.Image | None = None,
) -> Image.Image:
    """渲染对比拼图：原图 | [preprocess] | L | R（单页时省略 R 列）。

    v1.9+：当 ``preprocessed`` 不为 None 时，插入第 1 列（"PREPROCESS"）。
    其余列逻辑不变。

    Args:
        original: preprocess+deskew 后的原图（RGB；v1.9 之前是 deskew 后）。
        preprocessed: v1.9+：仅 preprocess 后、deskew 前的图（RGB/L）。
            ``None`` → 不插入 preprocess 列（v1.8 行为）。
        left/right: split 后的两页（None = single-page 模式）
        meta: ``{"source": str, "page_idx": int, "split_x": int | None,
               "deskew_angle": float | None, "size_in": tuple}``
        target_height: 每列目标高度（默认 800px）

    Returns:
        RGB Image（标题区 + 拼接区）
    """
    columns: list[Image.Image] = [original.convert("RGB") if original.mode != "RGB" else original]
    titles: list[str] = [f"ORIGINAL\n{meta.get('source', '?')} p{meta.get('page_idx', '?')}"]
    if meta.get("size_in"):
        titles[-1] += f"\n{meta['size_in'][0]}x{meta['size_in'][1]}"

    # v1.9+：preprocess 列（在 ORIGINAL 之后、L/R 之前）
    if preprocessed is not None:
        columns.append(
            preprocessed.convert("RGB") if preprocessed.mode != "RGB" else preprocessed
        )
        pp_chain = meta.get("preprocess_chain") or []
        pp_quality = meta.get("preprocess_quality") or "?"
        title = "PREPROCESS"
        if pp_chain:
            title += f"\n{','.join(pp_chain)}"
        title += f"\nquality={pp_quality}"
        titles.append(title)

    if left is not None:
        columns.append(left.convert("RGB") if left.mode != "RGB" else left)
        titles.append(f"PAGE L\n{meta.get('size_left', '?')}")
    if right is not None:
        columns.append(right.convert("RGB") if right.mode != "RGB" else right)
        titles.append(f"PAGE R\n{meta.get('size_right', '?')}")

    # 等高对齐 + 限宽
    columns = _fit_columns(columns, target_height)

    # 拼图高度 = max column 高 + 标题区
    col_h = max(c.size[1] for c in columns)
    total_w = sum(c.size[0] for c in columns) + COLUMN_PADDING * (len(columns) + 1)
    total_h = col_h + TITLE_HEIGHT + COLUMN_PADDING * 2

    canvas = Image.new("RGB", (total_w, total_h), "white")
    draw = ImageDraw.Draw(canvas)

    # 标题区
    for i, (col, title) in enumerate(zip(columns, titles, strict=True)):
        x = COLUMN_PADDING + sum(c.size[0] for c in columns[:i]) + COLUMN_PADDING * i
        y = 0
        # 标题文字
        for j, line in enumerate(title.split("\n")):
            draw.text((x + 4, 4 + j * 18), line, fill="black")
        # 列图
        canvas.paste(col, (x, TITLE_HEIGHT))

    # 在 ORIGINAL 列画 split line（红虚线）
    split_x = meta.get("split_x")
    if split_x is not None and meta.get("size_in"):
        size_in = meta["size_in"]
        original_col_idx = 0  # ORIGINAL 在第 0 列
        col_x_offset = COLUMN_PADDING + sum(
            c.size[0] for c in columns[:original_col_idx]
        ) + COLUMN_PADDING * original_col_idx
        # 等比映射 size_in → 实际列宽（v1.9+ ORIGINAL 列 index 不变；PREPROCESS 在其后）
        col_w, col_h_actual = columns[original_col_idx].size
        sx_ratio = col_w / size_in[0] if size_in[0] else 0
        sx_canvas = int(round(col_x_offset + split_x * sx_ratio))
        # 红色虚线（5 段：画 5px 实线 + 5px 间隔）
        y_top = TITLE_HEIGHT
        y_bot = TITLE_HEIGHT + col_h_actual
        for y in range(y_top, y_bot, 10):
            draw.line([(sx_canvas, y), (sx_canvas, min(y + 5, y_bot))], fill=SPLIT_LINE_COLOR, width=2)

    return canvas


def _serialize_page(page: dict) -> dict:
    """把单页 metrics dict 序列化为 JSON-friendly 形式。"""
    out: dict[str, Any] = {}
    for k, v in page.items():
        if isinstance(v, Image.Image):
            continue  # 不序列化 PIL Image
        if isinstance(v, tuple):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def write_preview(
    preview_dir: Path,
    compare_images: list[tuple[int, Image.Image]],  # [(page_idx, compare_pil), ...]
    pages_metrics: list[dict],
    summary: dict,
) -> Path:
    """把预览产物写到 ``preview_dir``。

    文件：
    - ``preview_p{idx:04d}_compare.png``：每页拼图
    - ``preview_summary.json``：汇总（含 pages 数组）
    - ``README.txt``：简要说明
    """
    preview_dir.mkdir(parents=True, exist_ok=True)

    # 拼图 PNG
    for page_idx, compare_img in compare_images:
        out_png = preview_dir / f"preview_p{page_idx + 1:04d}_compare.png"
        compare_img.save(out_png, format="PNG")

    # summary.json（含 pages 数组）
    summary_copy = dict(summary)
    summary_copy["pages"] = [_serialize_page(p) for p in pages_metrics]
    summary_path = preview_dir / "preview_summary.json"
    summary_path.write_text(
        json.dumps(summary_copy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # README.txt
    readme = (
        "book-cut v1.8 dry-run 预览\n"
        "\n"
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"输入: {summary.get('input', {}).get('path', '?')}\n"
        f"采样页数: {summary.get('input', {}).get('sampled_pages', '?')} "
        f"/ {summary.get('input', {}).get('total_pages', '?')}\n"
        "\n"
        "文件说明：\n"
        "- preview_p{N}_compare.png: 第 N 张采样页的对比拼图（原图 | L | R）\n"
        "- preview_summary.json: 完整指标汇总（配置 + 每页 metrics + 调参建议）\n"
        "\n"
        "拼图读法：\n"
        "- 红色虚线 = split column 位置（仅 ORIGINAL 列画）\n"
        "- 偏左/偏右 = gutter 找错中缝；偏离 > 20% 建议换 --split border\n"
        "- L/R 列如果有大块白边 = crop 没切紧；建议加 --crop-adaptive auto\n"
    )
    (preview_dir / "README.txt").write_text(readme, encoding="utf-8")

    return preview_dir


def compute_summary(
    input_path: str | Path,
    config: dict,
    sample_indices: list[int],
    total_pages: int,
    pages_metrics: list[dict],
    elapsed_ms: dict,
    paper_color: int | None = None,
) -> dict:
    """汇总 dry-run 结果为 summary dict。

    Args:
        input_path: 输入路径（str 或 Path）
        config: 实际跑的 config（split / crop / binarize / deskew / page_order）
        sample_indices: 采样页序号列表（0-based）
        total_pages: 输入总页数（PDF 走 iter_pages / 文件夹走递归 / 单图=1）
        pages_metrics: 每页 metrics dict 列表
        elapsed_ms: ``{"total": int, "per_page_avg": int, "estimated_full": int}``
        paper_color: 书级 paper color 估计（v1.3+ crop_config）
    """
    pages_with_warnings: list[int] = []
    for p in pages_metrics:
        if p.get("warnings"):
            pages_with_warnings.append(p.get("page_idx", -1))

    suggestion = _build_suggestion(pages_metrics)

    return {
        "tool": "book-cut",
        "version": "1.8.0",
        "mode": "dry-run",
        "input": {
            "path": str(input_path),
            "total_pages": total_pages,
            "sampled_pages": len(sample_indices),
            "sample_indices": sample_indices,
        },
        "config": config,
        "elapsed_ms": elapsed_ms,
        "paper_color_estimate": paper_color,
        "pages_with_warnings": pages_with_warnings,
        "suggestion": suggestion,
    }


def _build_suggestion(pages_metrics: list[dict]) -> str:
    """基于 per-page confidence + warning 拼出 1-2 句建议。"""
    if not pages_metrics:
        return ""

    confidences: list[tuple[int, float]] = []
    for p in pages_metrics:
        sp = p.get("split", {})
        if isinstance(sp, dict) and "confidence" in sp:
            confidences.append((p.get("page_idx", -1), float(sp["confidence"])))

    low_conf = [(i, c) for i, c in confidences if c < 0.5]
    if not low_conf:
        return "所有采样页 split confidence 良好，无调参建议"

    pages_str = ", ".join(f"p{i + 1}" for i, _ in low_conf[:3])
    return (
        f"{pages_str} split confidence 偏低（< 0.5），建议："
        "1) 改用 --split border；2) 或加大 --gutter-search-range（默认 0.4）；"
        "3) 或先 --deskew 后再 split"
    )
