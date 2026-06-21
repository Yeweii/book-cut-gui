"""输入加载：PDF / 单图 / 嵌套文件夹统一为 PageInfo 流。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

# 支持的图片扩展名（小写）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTS = {".pdf"}


@dataclass
class PageInfo:
    """统一的"页"抽象。

    Attributes:
        image: PIL Image（RGB）。
        source_name: 来源标识（PDF 文件名 / 图片文件名 / 文件夹名）。
        page_index: 在来源中的页序号（PDF 从 0 开始，图片固定 0）。
    """

    image: Image.Image
    source_name: str
    page_index: int


def _is_pdf(path: Path) -> bool:
    return path.suffix.lower() in PDF_EXTS


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def _load_image(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _iter_pdf(pdf_path: Path, dpi: int = 300) -> Iterator[PageInfo]:
    """流式遍历 PDF 每一页。"""
    import pymupdf  # 延迟导入：未用到 PDF 时无需该依赖

    doc = pymupdf.open(pdf_path)
    source_name = pdf_path.stem
    try:
        zoom = dpi / 72.0
        mat = pymupdf.Matrix(zoom, zoom)
        for idx, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            yield PageInfo(image=img, source_name=source_name, page_index=idx)
    finally:
        doc.close()


def _iter_image_file(path: Path) -> Iterator[PageInfo]:
    yield PageInfo(image=_load_image(path), source_name=path.stem, page_index=0)


def _iter_folder(folder: Path) -> Iterator[PageInfo]:
    """递归遍历文件夹：先 PDF（按文件名），再图片（按文件名）。"""
    pdfs = sorted(p for p in folder.rglob("*") if p.is_file() and _is_pdf(p))
    images = sorted(p for p in folder.rglob("*") if p.is_file() and _is_image(p))

    for p in pdfs:
        yield from _iter_pdf(p)
    for p in images:
        yield from _iter_image_file(p)


def iter_pages(source: str | Path) -> Iterator[PageInfo]:
    """根据路径类型分发到对应加载器。

    - 目录 → 递归加载所有 PDF 与图片
    - .pdf → 逐页加载
    - 图片文件 → 加载为单页
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"输入路径不存在: {path}")

    if path.is_dir():
        return _iter_folder(path)
    if _is_pdf(path):
        return _iter_pdf(path)
    if _is_image(path):
        return _iter_image_file(path)
    raise ValueError(f"不支持的输入类型: {path}")
