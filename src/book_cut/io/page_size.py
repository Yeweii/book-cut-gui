"""PDF 页面统一尺寸（v1.7）。

职责：
- ``PRESETS``：标准预设表（统一 mm 存储）
- ``parse()``：解析 ``--pdf-page-size`` 字符串，返回 ``(W, H)`` 像素元组
- ``fit_to_canvas()``：把任意尺寸图等比 fit + 居中 paste 到 (W, H) 画布

非 PDF 模式 (``--pdf-page-size`` 开启但 ``--pdf`` 未开) 由 caller 负责 warn
并 keep；本模块只关心 token → 像素尺寸映射。
"""

from __future__ import annotations

from PIL import Image

# ----------------------------------------------------------------------------
# 预设表（统一 mm 存储）
# ----------------------------------------------------------------------------

#: 标准预设，``宽×高`` 单位 mm。
#: token → (width_mm, height_mm)
PRESETS: dict[str, tuple[float, float]] = {
    "a4": (210.0, 297.0),
    "a5": (148.0, 210.0),
    "letter": (215.9, 279.4),  # 8.5 × 11 inch
    "legal": (215.9, 355.6),  # 8.5 × 14 inch
    # v2.3.3+：Amazon Kindle Paperwhite 6（11 代，2021 年）
    # 6.8" E Ink Carta 1200 @ 300 ppi → 1648×1232 px = 5.493×4.107 in
    # = 139.5 × 104.3 mm（display 区域，不含边框）
    "kpw6": (139.5, 104.3),
}

#: ``--pdf-page-size`` argparse choices（"keep" / "max" / "first" / 预设 / "custom"）。
PDF_PAGE_SIZE_CHOICES: tuple[str, ...] = (
    "keep",
    "max",
    "first",
    "a4",
    "a5",
    "letter",
    "legal",
    "kpw6",
    "custom",
)

#: ``--pdf-page-unit`` argparse choices（仅 ``--pdf-page-size custom`` 生效）。
PDF_PAGE_UNIT_CHOICES: tuple[str, ...] = ("mm", "cm", "inch", "px")

#: px 转换约定：1 inch = 96 px = 25.4 mm（与 img2pdf 默认一致）。
PX_PER_INCH: float = 96.0
MM_PER_INCH: float = 25.4


def _mm_to_px(value: float, unit: str) -> float:
    """把 ``value`` 从 ``unit`` 换算到像素（96 DPI）。"""
    if unit == "mm":
        return value / MM_PER_INCH * PX_PER_INCH
    if unit == "cm":
        return value * 10.0 / MM_PER_INCH * PX_PER_INCH
    if unit == "inch":
        return value * PX_PER_INCH
    if unit == "px":
        return value
    raise ValueError(f"未知单位: {unit}")


def parse_page_size_px(token: str, dim: str | None = None, unit: str = "mm") -> tuple[int, int]:
    """解析 ``--pdf-page-size`` token，返回 ``(W, H)`` 像素元组。

    Args:
        token: ``"a4"`` / ``"a5"`` / ``"letter"`` / ``"legal"`` / ``"custom"``。
        dim: ``--pdf-page-dim`` 字符串，``"WxH"``（仅 ``token=="custom"`` 时用）。
        unit: ``--pdf-page-unit`` 字符串（仅 ``token=="custom"`` 时用）。

    Returns:
        ``(width_px, height_px)``（四舍五入到整数像素）。

    Raises:
        ValueError: 未知 token / 缺 dim / dim 格式错 / 任意维度 ≤ 0。
    """
    if token in PRESETS:
        w_mm, h_mm = PRESETS[token]
        return (
            int(round(_mm_to_px(w_mm, "mm"))),
            int(round(_mm_to_px(h_mm, "mm"))),
        )
    if token == "custom":
        if not dim:
            raise ValueError("--pdf-page-size custom 需要配合 --pdf-page-dim (如 280x200)")
        try:
            parts = dim.lower().replace(" ", "").split("x")
            if len(parts) != 2:
                raise ValueError
            w_val = float(parts[0])
            h_val = float(parts[1])
        except (ValueError, IndexError) as e:
            raise ValueError(
                f"--pdf-page-dim 格式错: {dim!r}（期望 'WxH'，如 '280x200'）"
            ) from e
        if w_val <= 0 or h_val <= 0:
            raise ValueError(f"--pdf-page-dim 维度必须 > 0（got {dim}）")
        if unit not in PDF_PAGE_UNIT_CHOICES:
            raise ValueError(f"--pdf-page-unit 必须是 {PDF_PAGE_UNIT_CHOICES} 之一（got {unit!r}）")
        return (
            int(round(_mm_to_px(w_val, unit))),
            int(round(_mm_to_px(h_val, unit))),
        )
    raise ValueError(f"未知 --pdf-page-size: {token!r}（合法: {PDF_PAGE_SIZE_CHOICES}）")


# ----------------------------------------------------------------------------
# 图片 fit 策略
# ----------------------------------------------------------------------------


def fit_to_canvas(
    img: Image.Image,
    target_w: int,
    target_h: int,
    bg: int = 255,
) -> Image.Image:
    """把 ``img`` 等比 fit + 居中 paste 到 ``(target_w, target_h)`` 画布。

    Args:
        img: 输入图（任意 PIL mode）。长边贴合目标短边，缩放比例 = ``min(W/w, H/h)``。
        target_w: 目标宽度像素。
        target_h: 目标高度像素。
        bg: 画布背景色（0-255，灰度 / RGB 都用单值，PIL 自动广播）。

    Returns:
        新画布 Image（mode 与 ``img`` 一致，size = ``(target_w, target_h)``）。

    Note:
        子图与目标同尺寸时 ``scale == 1``，等价于原图 copy 到画布。
    """
    w, h = img.size
    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    fitted = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new(img.mode, (target_w, target_h), bg)
    canvas.paste(fitted, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas
