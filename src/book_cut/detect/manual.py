"""v2.3 手动裁切：独立奇偶页 ManualCropProfile + apply_manual_crop。

提供 manual crop 的核心能力：
- ``PageCropProfile``：单页 4 个 padding（v2.3+ 新增）
- ``ManualCropProfile``：``odd_page`` + ``even_page`` 两个独立 profile（v2.3+ 替代 mirror_even）
- ``apply_manual_crop(arr, profile, is_even)``：按 ``is_even`` 选对应 profile 切出子图
- ``parse_manual_padding(s)``：CLI 字符串 → 4 个 int
- ``canvas_to_image`` / ``padding_from_rect``：拖框数学（v2.3+ ``padding_from_rect`` 返回
  ``PageCropProfile``，无 mirror 参数）

v2.3+：与 v2.2 相比，去掉 ``mirror_even`` 镜像。镜像假设"奇偶页物理对称"在真实古籍中
常不成立（鱼尾形态、版心位置、版框残缺不对称），独立裁切更准。JSON preset v1 格式
通过 ``from_json`` 自动迁移到内存中的 v2 结构。

当 ``--crop manual`` 时完全接管裁切步骤（与 auto 互斥）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class PageCropProfile:
    """v2.3+ 单页 4 个 padding。

    Attributes:
        top: 顶部裁掉多少 px（从顶边向内数）。
        bottom: 底部裁掉多少 px（从底边向内数）。
        inner: 中缝侧裁掉多少 px（odd 页 = 左边；even 页 = 右边）。
        outer: 外侧裁掉多少 px（odd 页 = 右边；even 页 = 左边）。
    """

    top: int
    bottom: int
    inner: int
    outer: int


@dataclass(frozen=True)
class ManualCropProfile:
    """v2.3+ 手动裁切 profile：双 PageCropProfile 替代旧 mirror_even。

    Attributes:
        odd_page: 奇页 padding（split 输出 [左, 右] 中右页 i=1）。
        even_page: 偶页 padding（split 输出 [左, 右] 中左页 i=0）。
        source_size: 记录原图 (W, H)，跨书校验用；``None`` 表示不校验。
        notes: 用户注释（仅展示，不参与裁切计算）。
    """

    odd_page: PageCropProfile
    even_page: PageCropProfile
    source_size: tuple[int, int] | None = None
    notes: str = ""

    # JSON schema version
    _SCHEMA_VERSION: int = field(default=2, init=False, repr=False, compare=False)

    def to_json(self) -> str:
        """序列化为 v2 JSON 字符串。"""
        data: dict[str, Any] = {
            "version": self._SCHEMA_VERSION,
            "odd_page": {
                "top": self.odd_page.top,
                "bottom": self.odd_page.bottom,
                "inner": self.odd_page.inner,
                "outer": self.odd_page.outer,
            },
            "even_page": {
                "top": self.even_page.top,
                "bottom": self.even_page.bottom,
                "inner": self.even_page.inner,
                "outer": self.even_page.outer,
            },
            "source_size": list(self.source_size) if self.source_size is not None else None,
            "notes": self.notes,
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=False)

    @classmethod
    def from_json(cls, s: str) -> ManualCropProfile:
        """从 JSON 字符串反序列化（v2.3+ 兼容 v1）。

        支持：
        - v2 新格式：``{"odd_page": {...}, "even_page": {...}, "version": 2}``
        - v1 简洁：``{"top":50, "bottom":40, "inner":80, "outer":30, "mirror_even":true}``
        - v1 嵌套：``{"odd_page": {"top":50,...}, "mirror_even":true, ...}``
        """
        data = json.loads(s)
        version = data.get("version", 1)

        if version >= 2 and "odd_page" in data and "even_page" in data:
            # v2 新格式（odd_page + even_page 都是 dict）
            op, ep = data["odd_page"], data["even_page"]
            odd = PageCropProfile(
                top=int(op["top"]), bottom=int(op["bottom"]),
                inner=int(op["inner"]), outer=int(op["outer"]),
            )
            even = PageCropProfile(
                top=int(ep["top"]), bottom=int(ep["bottom"]),
                inner=int(ep["inner"]), outer=int(ep["outer"]),
            )
        else:
            # v1 兼容：自动迁移到 v2 双 profile 结构
            if "odd_page" in data and isinstance(data["odd_page"], dict):
                # v1 嵌套格式（odd_page 是 dict）
                od = data["odd_page"]
                top, bottom, inner, outer = (
                    int(od["top"]), int(od["bottom"]),
                    int(od["inner"]), int(od["outer"]),
                )
            else:
                # v1 简洁格式
                top, bottom, inner, outer = (
                    int(data["top"]), int(data["bottom"]),
                    int(data["inner"]), int(data["outer"]),
                )
            odd = PageCropProfile(top=top, bottom=bottom, inner=inner, outer=outer)
            mirror = bool(data.get("mirror_even", True))
            if mirror:
                # v1 mirror_even=True 等价于 v2 偶页 = 镜像（inner↔outer 互换）
                even = PageCropProfile(top=top, bottom=bottom, inner=outer, outer=inner)
            else:
                even = odd  # v1 mirror_even=False 等价于 v2 偶页 = 奇页

        ss = data.get("source_size")
        return cls(
            odd_page=odd,
            even_page=even,
            source_size=(int(ss[0]), int(ss[1])) if ss is not None else None,
            notes=str(data.get("notes", "")),
        )


def apply_manual_crop(
    arr: np.ndarray,
    profile: ManualCropProfile,
    is_even: bool = False,
) -> np.ndarray:
    """按 profile 切出子图（v2.3+）。

    Args:
        arr: 灰度 ndarray（已切分后的子图）。
        profile: 手动裁切配置（双 PageCropProfile 结构）。
        is_even: 是否偶页（影响选 ``odd_page`` 还是 ``even_page``）。

    Returns:
        裁切后的 ndarray。

    Raises:
        ValueError: padding 越界（``top+bottom >= H`` 或 ``inner+outer >= W``）。
    """
    p = profile.even_page if is_even else profile.odd_page
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
    if p.top + p.bottom >= h:
        raise ValueError(
            f"top+bottom ({p.top + p.bottom}) >= height ({h})"
        )
    if p.inner + p.outer >= w:
        raise ValueError(
            f"inner+outer ({p.inner + p.outer}) >= width ({w})"
        )

    # v2.3+：奇偶页 inner/outer 语义不同
    #   奇页：inner = 左边留白 → L = inner；outer = 右边留白 → R = W - outer
    #   偶页：inner = 右边留白 → R = W - inner；outer = 左边留白 → L = outer
    if is_even:
        return arr[p.top : h - p.bottom, p.outer : w - p.inner]
    return arr[p.top : h - p.bottom, p.inner : w - p.outer]


def canvas_to_image(cx: float, cy: float, scale: float) -> tuple[int, int]:
    """Canvas 坐标 → 原图坐标（v2.3+ 拖框数学，无变化）。

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
) -> PageCropProfile:
    """矩形（image 坐标）→ PageCropProfile（v2.3+：无 mirror 参数）。

    Args:
        rect_in_image: ``(L, T, R, B)``，原图坐标系下的矩形边界。
        img_size: ``(W, H)``，原图尺寸。
        is_even: 是否偶页（决定 inner/outer 互换方向）。

    Returns:
        PageCropProfile（4 个 padding）。
    """
    L, T, R, B = rect_in_image
    W, H = img_size
    top = T
    bottom = H - B
    if is_even:
        # 偶页：inner = 右边留白 = W - R；outer = 左边留白 = L
        inner = W - R
        outer = L
    else:
        # 奇页：inner = 左边留白 = L；outer = 右边留白 = W - R
        inner = L
        outer = W - R
    return PageCropProfile(top=top, bottom=bottom, inner=inner, outer=outer)


def parse_manual_padding(s: str) -> tuple[int, int, int, int]:
    """解析 ``--manual-odd-padding`` / ``--manual-even-padding`` 字符串 → ``(top, bottom, inner, outer)``。

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
