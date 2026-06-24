"""v2.2 手动裁切：ManualCropProfile + apply_manual_crop。

提供 manual crop 的核心能力：
- ``ManualCropProfile``：4 个 padding + mirror_even + source_size + notes
- ``apply_manual_crop(arr, profile, is_even)``：按 profile 切出子图（偶页自动镜像 inner/outer）

v2.2+：与 auto crop（trim / border）互不替代；
当 ``--crop manual`` 时完全接管裁切步骤。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class ManualCropProfile:
    """手动裁切 profile。

    Attributes:
        top: 顶部裁掉多少 px（从顶边向内数）。
        bottom: 底部裁掉多少 px（从底边向内数）。
        inner: 中缝侧裁掉多少 px（odd 页 = 左边）。
        outer: 外侧裁掉多少 px（odd 页 = 右边）。
        mirror_even: 偶页是否自动 inner↔outer 镜像。
        source_size: 记录原图 (W, H)，跨书校验用；``None`` 表示不校验。
        notes: 用户注释（仅展示，不参与裁切计算）。
    """

    top: int
    bottom: int
    inner: int
    outer: int
    mirror_even: bool = True
    source_size: tuple[int, int] | None = None
    notes: str = ""

    # JSON schema version
    _SCHEMA_VERSION: int = field(default=1, init=False, repr=False, compare=False)

    def to_json(self) -> str:
        """序列化为 JSON 字符串。"""
        data: dict[str, Any] = {
            "version": self._SCHEMA_VERSION,
            "top": self.top,
            "bottom": self.bottom,
            "inner": self.inner,
            "outer": self.outer,
            "mirror_even": self.mirror_even,
            "source_size": list(self.source_size) if self.source_size is not None else None,
            "notes": self.notes,
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_json(cls, s: str) -> ManualCropProfile:
        """从 JSON 字符串反序列化。

        支持两种 schema：
        - 简洁：``{"top":50, "bottom":40, "inner":80, "outer":30, ...}``
        - 嵌套：``{"odd_page": {"top":50, ...}, "mirror_even": true, "name": "...", ...}``
        """
        data = json.loads(s)
        if "odd_page" in data:
            # 嵌套格式
            od = data["odd_page"]
            top, bottom, inner, outer = (
                int(od["top"]), int(od["bottom"]), int(od["inner"]), int(od["outer"])
            )
        else:
            # 简洁格式
            top, bottom, inner, outer = (
                int(data["top"]), int(data["bottom"]),
                int(data["inner"]), int(data["outer"]),
            )
        ss = data.get("source_size")
        return cls(
            top=top,
            bottom=bottom,
            inner=inner,
            outer=outer,
            mirror_even=bool(data.get("mirror_even", True)),
            source_size=(int(ss[0]), int(ss[1])) if ss is not None else None,
            notes=str(data.get("notes", "")),
        )


def apply_manual_crop(
    arr: np.ndarray,
    profile: ManualCropProfile,
    is_even: bool = False,
) -> np.ndarray:
    """按 profile 切出子图（v2.2+）。

    Args:
        arr: 灰度 ndarray（已切分后的子图）。
        profile: 手动裁切配置。
        is_even: 是否偶页（影响 inner/outer 方向，仅在 ``profile.mirror_even=True`` 时生效）。

    Returns:
        裁切后的 ndarray。

    Raises:
        ValueError: padding 越界（``top+bottom >= H`` 或 ``inner+outer >= W``）。
    """

    h, w = arr.shape[:2]

    # source_size 校验：跨书复用 preset 时提示
    if profile.source_size is not None:
        sw, sh = profile.source_size
        if (sw, sh) != (w, h):
            logging.warning(
                "manual crop source_size mismatch: profile=(%d,%d) actual=(%d,%d). "
                "Padding 是绝对像素，可能与当前图不匹配；已按当前图继续裁切。",
                sw, sh, w, h,
            )
    if profile.top + profile.bottom >= h:
        raise ValueError(
            f"top+bottom ({profile.top + profile.bottom}) >= height ({h})"
        )
    if profile.inner + profile.outer >= w:
        raise ValueError(
            f"inner+outer ({profile.inner + profile.outer}) >= width ({w})"
        )

    if is_even and profile.mirror_even:
        # 偶页镜像：inner↔outer 互换
        top, bottom = profile.top, profile.bottom
        left = profile.outer
        right = w - profile.inner
    else:
        # 奇页（或 mirror_even=False）：正常
        top, bottom = profile.top, profile.bottom
        left = profile.inner
        right = w - profile.outer

    return arr[top : h - bottom, left:right]


def canvas_to_image(cx: float, cy: float, scale: float) -> tuple[int, int]:
    """Canvas 坐标 → 原图坐标（v2.2+ 拖框数学）。

    Args:
        cx, cy: Canvas 上的像素坐标。
        scale: 原图 / Canvas 的缩放比（> 1 表示原图更大，< 1 表示 Canvas 更大）。

    Returns:
        (ix, iy)：原图像素坐标（亚像素向下取整）。
    """
    if scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale}")
    return int(cx / scale), int(cy / scale)


def padding_from_rect(
    rect_in_image: tuple[int, int, int, int],
    img_size: tuple[int, int],
    is_even: bool,
    mirror_even: bool,
) -> tuple[int, int, int, int]:
    """矩形（image 坐标）→ 4 个 padding（top, bottom, inner, outer）（v2.2+）。

    Args:
        rect_in_image: ``(L, T, R, B)``，原图坐标系下的矩形边界。
        img_size: ``(W, H)``，原图尺寸。
        is_even: 是否偶页。
        mirror_even: 偶页是否镜像 inner/outer。

    Returns:
        ``(top, bottom, inner, outer)``。
    """
    L, T, R, B = rect_in_image
    W, H = img_size
    top = T
    bottom = H - B
    if is_even and mirror_even:
        # 偶页镜像
        inner = W - R
        outer = L
    else:
        inner = L
        outer = W - R
    return top, bottom, inner, outer


def parse_manual_padding(s: str) -> tuple[int, int, int, int]:
    """解析 ``--manual-odd-padding`` 字符串 → ``(top, bottom, inner, outer)``（v2.2+）。

    支持两种格式：
    - 位置式（顺序 T,B,I,O）：``"50,40,80,30"``
    - 键值式：``"T=50,B=40,I=80,O=30"``（顺序任意）

    Args:
        s: 用户输入的字符串。

    Returns:
        ``(top, bottom, inner, outer)`` 4 个 int。

    Raises:
        ValueError: 格式错误或字段不全。
    """
    if s is None or s.strip() == "":
        raise ValueError("manual padding 字符串为空")

    s = s.strip()
    parts = [p.strip() for p in s.split(",") if p.strip()]

    if len(parts) == 4 and all("=" not in p for p in parts):
        # 位置式
        try:
            vals = [int(p) for p in parts]
        except ValueError as e:
            raise ValueError(
                f"manual padding 解析失败: {s!r}（期望 4 个整数或 K=V 对）"
            ) from e
        if any(v < 0 for v in vals):
            raise ValueError(f"manual padding 不能为负: {vals}")
        return vals[0], vals[1], vals[2], vals[3]

    # 键值式
    kv: dict[str, int] = {}
    for p in parts:
        if "=" not in p:
            raise ValueError(
                f"manual padding 格式错误: {p!r}（期望 K=V 形式）"
            )
        k, v = p.split("=", 1)
        k = k.strip().upper()
        v = v.strip()
        if k not in ("T", "B", "I", "O"):
            raise ValueError(
                f"manual padding 未知字段: {k!r}（期望 T/B/I/O）"
            )
        try:
            kv[k] = int(v)
        except ValueError as e:
            raise ValueError(f"manual padding {k}={v!r} 不是整数") from e
    missing = {"T", "B", "I", "O"} - kv.keys()
    if missing:
        raise ValueError(
            f"manual padding 缺少字段: {sorted(missing)}（期望 T/B/I/O 全有）"
        )
    if any(v < 0 for v in kv.values()):
        raise ValueError(f"manual padding 不能为负: {kv}")
    return kv["T"], kv["B"], kv["I"], kv["O"]
