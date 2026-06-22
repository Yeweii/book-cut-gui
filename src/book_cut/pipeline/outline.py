"""outline / metadata：PDF 来源解析 + 合并 PDF 写出。

职责：
- ``_resolve_outline_source(input_path)``：决定 outline / metadata 来源 PDF
- ``_first_and_count_pdfs(folder)``：单次扫描拿 PDF 列表（v1.6+ A4）
- ``_write_pdf_with_outline(...)``：img2pdf + pypdf 注入 outline（v1.4 + v1.5+ B2）

v1.6+ C3：从原 ``pipeline.py`` 拆出，独立模块。
"""

from __future__ import annotations

from pathlib import Path

from book_cut import __version__
from book_cut.io.exporter import (
    inject_outline_and_metadata_from_bytes,
    save_pdf_bytes,
)


def _resolve_outline_source(input_path: Path) -> tuple[Path | None, bool]:
    """决定 outline / metadata 的来源 PDF。

    v1.6+ A4：单次目录扫描拿到 (first_pdf, count)，替代原来
    ``first_pdf_in_folder`` + 手动 ``rglob("*.pdf")`` + ``rglob("*.PDF")``
    三次扫描。

    Returns:
        ``(pdf_path, is_folder_multi)``：
        - 单文件 PDF → ``(path, False)``
        - 文件夹（含 ≥1 个 PDF）→ ``(first_pdf, True)``（多 PDF 时 log 警告）
        - 单图 / 文件夹无 PDF → ``(None, False)``
    """
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return input_path, False
    if input_path.is_dir():
        first, count = _first_and_count_pdfs(input_path)
        if first is None:
            return None, False
        return first, count > 1
    return None, False


def _first_and_count_pdfs(folder: Path) -> tuple[Path | None, int]:
    """v1.6+ A4：单次扫描拿第一个 PDF + 计数（替代 ``first_pdf_in_folder`` + 重复 rglob）。

    用 ``rglob("*")`` + ``_is_pdf`` 过滤，与 ``first_pdf_in_folder`` 行为一致
    （大小写不敏感地识别 .pdf/.PDF）。

    Args:
        folder: 目录路径。

    Returns:
        ``(first_pdf, count)``：空目录时 ``(None, 0)``。
    """
    from book_cut.io.loader import _is_pdf

    pdfs = sorted(p for p in folder.rglob("*") if p.is_file() and _is_pdf(p))
    if not pdfs:
        return None, 0
    return pdfs[0], len(pdfs)


def _write_pdf_with_outline(
    image_paths: list[Path],
    pdf_path: Path,
    toc: list[tuple[int, str, int]],
    metadata: dict[str, str],
    mapping: dict[int, list[int]],
    enabled: bool,
) -> Path:
    """写出最终 PDF（v1.5+ B2：全内存，去 tempfile）。

    - ``enabled`` 且有 ``toc`` / ``metadata`` / ``mapping`` → img2pdf 出 bytes
      → pypdf 从 BytesIO 读 → 注入 outline + metadata → 写 ``pdf_path``
    - 否则 img2pdf bytes → 直接写 ``pdf_path``
    """
    if not (enabled and (toc or metadata) and mapping):
        pdf_bytes = save_pdf_bytes(image_paths)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pdf_bytes)
        return pdf_path

    pdf_bytes = save_pdf_bytes(image_paths)
    # producer 追加 book-cut 标识（透传的同时标记出处）
    meta = dict(metadata)
    if "/Producer" in meta:
        meta["/Producer"] = f"{meta['/Producer']}; book-cut {__version__}"
    else:
        meta["/Producer"] = f"book-cut {__version__}"
    return inject_outline_and_metadata_from_bytes(
        pdf_bytes, pdf_path, toc, meta, mapping
    )