"""输出：保存图片、合并 PDF（v1.4：可选注入 outline + metadata）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

ImageFormat = Literal["png", "jpg", "jpeg", "tif", "tiff", "webp"]

FORMAT_EXTS: dict[str, str] = {
    "png": ".png",
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "tif": ".tif",
    "tiff": ".tif",
    "webp": ".webp",
}

# pypdf ``/Info`` 字典的标准 key（pymupdf 的 doc.metadata 也是这套）
STANDARD_METADATA_KEYS = {
    "/Title",
    "/Author",
    "/Subject",
    "/Keywords",
    "/Creator",
    "/Producer",
    "/CreationDate",
    "/ModDate",
}


def save_image(
    image: Image.Image,
    output_dir: Path,
    book_name: str,
    index: int,
    fmt: ImageFormat = "png",
    quality: int = 95,
) -> Path:
    """保存单张图片，返回输出路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = FORMAT_EXTS.get(fmt, ".png")
    name = f"{book_name}_{index:04d}{ext}"
    out_path = output_dir / name

    save_kwargs: dict = {}
    if fmt in {"jpg", "jpeg", "webp"}:
        save_kwargs["quality"] = quality
        # JPG/WebP 不支持 L/LA/RGBA，统一转 RGB
        if image.mode not in {"RGB"}:
            image = image.convert("RGB")

    image.save(out_path, **save_kwargs)
    return out_path


def save_pdf(image_paths: list[Path], pdf_path: Path) -> Path:
    """把若干图片合并为 PDF（无损，无 outline/metadata）。"""
    try:
        import img2pdf
    except ImportError as e:
        raise RuntimeError("请先安装 img2pdf") from e

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths]))
    return pdf_path


# ----------------------------------------------------------------------------
# v1.4 新增：outline / metadata 后处理（基于 img2pdf 的中间 PDF）
# ----------------------------------------------------------------------------


def inject_outline_and_metadata(
    src_pdf: Path,
    dst_pdf: Path,
    toc: list[tuple[int, str, int]],
    metadata: dict[str, str],
    mapping: dict[int, list[int]],
) -> Path:
    """从 ``src_pdf``（img2pdf 生成的无 outline PDF）读取，
    按 ``mapping`` 重写 outline、注入 ``metadata``，写出到 ``dst_pdf``。

    Args:
        src_pdf: 输入 PDF 路径（img2pdf 产物，无 outline/metadata）。
        dst_pdf: 输出 PDF 路径。
        toc: 原 PDF 的 outline，``[(level, title, orig_page_1idx), ...]``。
        metadata: 原 PDF 的 ``/Info`` 字典（key 形如 ``"/Title"``）。
        mapping: ``orig_idx_0based → [out_idx_0based, ...]``。
            1:2 时取 ``mapping[i][0]``（"只指第一张"拍板）。

    Returns:
        ``dst_pdf``。
    """
    try:
        import pypdf
    except ImportError as e:
        raise RuntimeError("请先安装 pypdf") from e

    reader = pypdf.PdfReader(str(src_pdf))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    # 1. outline：按原顺序逐项添加，level>1 时挂到 parent
    # 跟踪最近一级 level 节点，作为后续子节点的 parent
    last_by_level: dict[int, object] = {}
    for level, title, orig_page_1idx in toc:
        orig_idx = orig_page_1idx - 1  # pymupdf 1-based → 0-based
        if orig_idx not in mapping:
            continue  # 原页没出现在输出中（理论上不应发生，防御一下）
        out_idx = mapping[orig_idx][0]  # 1:2 时只指第一张（拍板）
        if out_idx < 0 or out_idx >= len(writer.pages):
            continue
        parent = last_by_level.get(level - 1) if level > 1 else None
        item = writer.add_outline_item(title, out_idx, parent=parent)
        last_by_level[level] = item
        # 重置更深层：避免子节点挂错父
        for deeper in [k for k in last_by_level if k > level]:
            last_by_level.pop(deeper, None)

    # 2. metadata：只透传标准 key
    if metadata:
        safe = {k: v for k, v in metadata.items() if k in STANDARD_METADATA_KEYS}
        if safe:
            writer.add_metadata(safe)

    dst_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(dst_pdf, "wb") as f:
        writer.write(f)
    return dst_pdf
