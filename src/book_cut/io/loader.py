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


# ----------------------------------------------------------------------------
# v1.4 新增：PDF outline / metadata 抓取（独立于 PageInfo）
# ----------------------------------------------------------------------------

# pymupdf metadata 字段 → pypdf Info 字典键（带斜杠）映射
_METADATA_KEY_MAP: dict[str, str] = {
    "title": "/Title",
    "author": "/Author",
    "subject": "/Subject",
    "keywords": "/Keywords",
    "creator": "/Creator",
    "creationDate": "/CreationDate",
    "modDate": "/ModDate",
}


def get_pdf_outline(pdf_path: str | Path) -> list[tuple[int, str, int]]:
    """读取 PDF 顶层 outline（书签）树。

    Returns:
        ``[(level, title, page_1idx), ...]`` —— 与 pymupdf ``doc.get_toc()``
        同构（page 1-indexed）。空列表表示无 outline。
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        toc = doc.get_toc() or []
        # 转成 list[tuple] 以免调用方误以为是 pymupdf 内部类型
        return [(int(lvl), str(title), int(p1)) for lvl, title, p1 in toc]
    finally:
        doc.close()


def get_pdf_metadata(pdf_path: str | Path) -> dict[str, str]:
    """读取 PDF ``/Info`` metadata（title/author/creator 等）。

    Returns:
        ``{pypdf_key: value}``，key 形如 ``"/Title"``，可直接喂给
        ``PdfWriter.add_metadata``。空字段会被过滤掉。
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        raw = doc.metadata or {}
    finally:
        doc.close()
    out: dict[str, str] = {}
    for src_key, dst_key in _METADATA_KEY_MAP.items():
        val = raw.get(src_key)
        if val:  # 过滤 None / "" / 空串
            out[dst_key] = str(val)
    return out


def first_pdf_in_folder(folder: Path) -> Path | None:
    """递归查找 folder 内按文件名排序的第一个 PDF（用于多 PDF 源时取 outline）。"""
    pdfs = sorted(p for p in folder.rglob("*") if p.is_file() and _is_pdf(p))
    return pdfs[0] if pdfs else None


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


# ----------------------------------------------------------------------------
# v1.7 新增：流式产出每页 (width, height)，仅取尺寸不渲染
# ----------------------------------------------------------------------------


def _iter_pdf_page_sizes(pdf_path: Path) -> Iterator[tuple[int, int]]:
    """流式产出 PDF 每页 ``(width_pt, height_pt)``，不渲染。

    PDF ``Page.rect.width/height`` 单位是 points（1pt = 1/72 in）。
    """
    import pymupdf

    doc = pymupdf.open(pdf_path)
    try:
        for page in doc:
            r = page.rect
            yield (int(r.width), int(r.height))
    finally:
        doc.close()


def _iter_image_page_sizes(path: Path) -> Iterator[tuple[int, int]]:
    """产出单图 ``(width_px, height_px)``，不实际 load 像素。"""
    with Image.open(path) as img:
        yield (img.width, img.height)


def iter_page_sizes(source: str | Path) -> Iterator[tuple[int, int]]:
    """v1.7：流式产出每页 ``(width, height)``，供 ``--pdf-page-size max`` 预扫。

    - PDF: ``pymupdf.Page.rect.width/height``（points，1pt = 1/72 in）—— **不渲染**
    - 图片: ``Image.open(path).size`` 后 close（不实际 load 像素）
    - 文件夹: 递归（PDF 先按文件名，再图片按文件名，与 ``iter_pages`` 一致）

    为什么不直接复用 ``iter_pages``：那个会全量渲染成 RGB Image，对只需要尺寸
    的场景（max 预扫）慢 100×+。
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"输入路径不存在: {path}")

    if path.is_dir():
        # 与 _iter_folder 一致：先 PDF 再图片
        pdfs = sorted(p for p in path.rglob("*") if p.is_file() and _is_pdf(p))
        images = sorted(p for p in path.rglob("*") if p.is_file() and _is_image(p))
        for p in pdfs:
            yield from _iter_pdf_page_sizes(p)
        for p in images:
            yield from _iter_image_page_sizes(p)
        return
    if _is_pdf(path):
        yield from _iter_pdf_page_sizes(path)
        return
    if _is_image(path):
        yield from _iter_image_page_sizes(path)
        return
    raise ValueError(f"不支持的输入类型: {path}")
