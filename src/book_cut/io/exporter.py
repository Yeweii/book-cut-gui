"""输出：保存图片、合并 PDF。"""

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
    """把若干图片合并为 PDF（无损）。"""
    try:
        import img2pdf
    except ImportError as e:
        raise RuntimeError("请先安装 img2pdf") from e

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths]))
    return pdf_path
