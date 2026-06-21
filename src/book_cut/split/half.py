"""对半切：固定 w//2，支持 offset 微调。"""

from __future__ import annotations

from PIL import Image


def split_half(image: Image.Image, offset: int = 0) -> list[Image.Image]:
    """在 width//2 + offset 处切分，返回 [left, right]。"""
    w, _ = image.size
    if w < 2:
        raise ValueError(f"图像宽度过小: {w}")
    mid = max(1, min(w - 1, w // 2 + offset))
    return [image.crop((0, 0, mid, image.size[1])), image.crop((mid, 0, w, image.size[1]))]
