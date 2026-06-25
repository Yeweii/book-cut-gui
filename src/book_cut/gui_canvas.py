"""v2.2 GUI 拖框：可拖拽裁切框 Canvas。

提供 ``CropCanvas`` —— 在 ``tk.Canvas`` 上展示一张样本图，叠加可拖拽的
4 边 + 8 handle 矩形。拖动后实时把"保留区域"反算为 ``(top, bottom,
inner, outer)`` 4 个 padding，写回 ``ManualCropProfile``。

设计目标：
- 拖框数学与 GUI 解耦（``canvas_to_image`` / ``padding_from_rect``
  在 ``book_cut.detect.manual`` 中是纯函数，便于单测）
- Canvas 只负责：渲染 + 鼠标事件 + 状态更新
- 大图 downscale 到 ``max_display`` 像素内显示，原图坐标系保留
- 支持双击重置、Shift 锁定纵横比
"""

from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageTk

from book_cut.detect.manual import (
    ManualCropProfile,
    padding_from_rect,
)

try:
    import tkinter as tk
except ImportError:  # pragma: no cover — tkinter 不可用时 import 仍可成功
    tk = None  # type: ignore[assignment]


# 视觉常量
_HANDLE_SIZE = 8          # handle 边长（canvas 像素）
_EDGE_COLOR_TB = "#d62728"  # 顶/底边（红）
_EDGE_COLOR_IO = "#1f77b4"  # 内/外边（蓝）
_HANDLE_COLOR = "#ff7f0e"   # handle（橙）
_DIM_FILL = ""             # 框外区域填充（用 stipple 模拟半透明）
_DIM_STIPPLE = "gray50"


# 拖拽模式枚举
_DRAG_NONE = 0
_DRAG_MOVE = 1             # 框内整体平移
_DRAG_T = 2                # 顶边
_DRAG_B = 3                # 底边
_DRAG_I = 4                # 内边
_DRAG_O = 5                # 外边
_DRAG_TL = 6               # 左上角
_DRAG_TR = 7               # 右上角
_DRAG_BL = 8               # 左下角
_DRAG_BR = 9               # 右下角


class CropCanvas(tk.Canvas):  # type: ignore[misc, valid-type]
    """可拖拽裁切框 Canvas（v2.3+）。

    Args:
        parent: 父 widget。
        image: 原始图像（PIL.Image）。
        profile: 初始 ManualCropProfile（v2.3+ 含 odd_page + even_page）。
        is_even: 当前显示的是否偶页（影响内/外语义）。
        on_change: profile 变化时回调（接收新 profile）。
        max_display: 显示区域最大边长（像素）；原图按此 downscale。
    """

    MIN_RECT_SIZE = 100  # 最小矩形边长（image 像素）

    def __init__(
        self,
        parent,
        image: Image.Image,
        profile: ManualCropProfile,
        is_even: bool = False,
        on_change: Callable[[ManualCropProfile], None] | None = None,
        max_display: int = 1200,
        **kwargs,
    ) -> None:
        self._raw_image = image
        self._raw_w, self._raw_h = image.size
        # 计算 downscale
        scale_w = max_display / self._raw_w
        scale_h = max_display / self._raw_h
        self._scale = min(1.0, scale_w, scale_h)
        self._disp_w = int(self._raw_w * self._scale)
        self._disp_h = int(self._raw_h * self._scale)

        super().__init__(
            parent,
            width=self._disp_w,
            height=self._disp_h,
            highlightthickness=1,
            highlightbackground="#888",
            **kwargs,
        )

        # 状态（v2.3+：移除 _mirror_even；偶页方向由 profile.even_page 决定）
        self._is_even = is_even
        self._on_change = on_change
        self._drag_mode: int = _DRAG_NONE
        self._drag_anchor: tuple[int, int] = (0, 0)
        self._drag_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._photo: ImageTk.PhotoImage | None = None  # 防止被 GC
        self._image_item: int | None = None
        self._rect_items: list[int] = []
        self._handle_items: list[int] = []

        # 渲染图片
        self._draw_image()

        # v2.3+：保存原始 profile snapshot 以便 get_profile 保留另一侧 PageCropProfile
        self._profile_snapshot = profile

        # 从 profile 计算初始 rect
        self.set_profile(profile)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def set_profile(self, profile: ManualCropProfile) -> None:
        """设置 profile，重绘矩形（v2.3+）。"""
        self._profile_snapshot = profile
        p = profile.even_page if self._is_even else profile.odd_page
        t, b, i, o = p.top, p.bottom, p.inner, p.outer
        W, H = self._raw_w, self._raw_h
        # v2.3+：奇/偶页 inner/outer 语义不同
        #   奇页：inner = 左边留白 = L；outer = 右边留白 = W - R
        #   偶页：inner = 右边留白 = W - R；outer = 左边留白 = L
        if self._is_even:
            L, R = o, W - i
        else:
            L, R = i, W - o
        T, B = t, H - b
        # 边界 clamp（防 profile 越界）
        L = max(0, min(L, W - 1))
        R = max(L + 1, min(R, W))
        T = max(0, min(T, H - 1))
        B = max(T + 1, min(B, H))
        self._rect = (L, T, R, B)
        self._render_rect()

    def get_profile(self) -> ManualCropProfile:
        """从当前矩形反算 ManualCropProfile（v2.3+：返回双 PageCropProfile）。"""
        L, T, R, B = self._rect
        p = padding_from_rect(
            (L, T, R, B),
            (self._raw_w, self._raw_h),
            is_even=self._is_even,
        )
        # 当前 is_even 决定更新 odd 还是 even；另一边保留 snapshot 原值
        snap = self._profile_snapshot
        if self._is_even:
            new_even = p
            new_odd = snap.odd_page
        else:
            new_odd = p
            new_even = snap.even_page
        # 更新 snapshot（让下一次 get_profile 仍能看到本侧新值）
        self._profile_snapshot = ManualCropProfile(
            odd_page=new_odd,
            even_page=new_even,
            source_size=(self._raw_w, self._raw_h),
        )
        return self._profile_snapshot

    def reset(self) -> None:
        """双击重置：回到全图。"""
        self._rect = (0, 0, self._raw_w, self._raw_h)
        self._render_rect()
        self._notify_change()

    def set_is_even(self, is_even: bool) -> None:
        """切换奇/偶页（v2.3+：用对应 PageCropProfile 重新计算 rect）。"""
        self._is_even = is_even
        # 重新用当前 padding 应用新方向
        prof = self.get_profile()
        self.set_profile(prof)

    # ------------------------------------------------------------------
    # 缩放（v2.2.3+）：放大/缩小/适应窗口
    # ------------------------------------------------------------------

    def set_scale(self, scale: float) -> None:
        """设置显示 scale（v2.2.3+）。

        重算 ``_disp_w`` / ``_disp_h``，重新 config Canvas 尺寸 + 重绘图 + 重设 scrollregion。
        拖框 rect 在原图坐标系下保持不变，所以视觉效果是"放大/缩小查看"，
        padding 数学不变。
        """
        if scale <= 0:
            raise ValueError(f"scale must be > 0, got {scale}")
        self._scale = scale
        self._disp_w = max(1, int(self._raw_w * scale))
        self._disp_h = max(1, int(self._raw_h * scale))
        self.config(width=self._disp_w, height=self._disp_h)
        # 删旧图
        if self._image_item is not None:
            self.delete(self._image_item)
            self._image_item = None
        self._draw_image()
        self._render_rect()
        # 同步 scrollregion（让 Scrollbar 知道可滚动范围）
        self.config(scrollregion=(0, 0, self._disp_w, self._disp_h))

    def fit_to_size(self, max_w: int, max_h: int) -> None:
        """按 ``max_w × max_h`` 视口计算 best scale 并 set_scale（v2.2.3+）。

        scale = min(max_w/raw_w, max_h/raw_h, 1.0) —— 不放大原图。
        """
        if max_w <= 0 or max_h <= 0:
            raise ValueError(f"max_w/max_h must be > 0, got {max_w}x{max_h}")
        scale_w = max_w / self._raw_w
        scale_h = max_h / self._raw_h
        self.set_scale(min(1.0, scale_w, scale_h))

    def get_scale(self) -> float:
        """返回当前显示 scale。"""
        return self._scale

    def zoom_in(self, factor: float = 1.25) -> None:
        """放大（v2.2.3+）：scale × factor。"""
        self.set_scale(self._scale * factor)

    def zoom_out(self, factor: float = 1.25) -> None:
        """缩小（v2.2.3+）：scale / factor。"""
        self.set_scale(self._scale / factor)

    def zoom_reset(self) -> None:
        """重置到 1.0（原图大小，v2.2.3+）。"""
        self.set_scale(1.0)

    # ------------------------------------------------------------------
    # 鼠标事件
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        self._drag_anchor = (event.x, event.y)
        self._drag_rect = self._rect
        self._drag_mode = self._hit_test(event.x, event.y)
        if self._drag_mode == _DRAG_NONE:
            # 点击外部：当作 MOVE 也行（MOVE 模式下也会动）
            self._drag_mode = _DRAG_MOVE

    def _on_drag(self, event) -> None:
        if self._drag_mode == _DRAG_NONE:
            return
        # 计算 canvas 坐标位移 → 原图像素位移
        dx_canvas = event.x - self._drag_anchor[0]
        dy_canvas = event.y - self._drag_anchor[1]
        dx_img = int(dx_canvas / self._scale)
        dy_img = int(dy_canvas / self._scale)
        L, T, R, B = self._drag_rect
        new = self._apply_drag(self._drag_mode, L, T, R, B, dx_img, dy_img, event)
        # clamp + 最小尺寸
        new = self._clamp_rect(new)
        if new != self._rect:
            self._rect = new
            self._render_rect()
            self._notify_change()

    def _on_release(self, _event) -> None:
        self._drag_mode = _DRAG_NONE

    def _on_double_click(self, _event) -> None:
        self.reset()

    def _hit_test(self, cx: int, cy: int) -> int:
        """点击 (cx, cy) 命中哪个 handle / edge。"""
        L, T, R, B = self._rect
        # 矩形 → canvas 坐标
        cl = int(L * self._scale)
        ct = int(T * self._scale)
        cr = int(R * self._scale)
        cb = int(B * self._scale)
        hs = _HANDLE_SIZE
        # 4 角（优先）
        if abs(cx - cl) <= hs and abs(cy - ct) <= hs:
            return _DRAG_TL
        if abs(cx - cr) <= hs and abs(cy - ct) <= hs:
            return _DRAG_TR
        if abs(cx - cl) <= hs and abs(cy - cb) <= hs:
            return _DRAG_BL
        if abs(cx - cr) <= hs and abs(cy - cb) <= hs:
            return _DRAG_BR
        # 4 边
        if cl - hs <= cx <= cr + hs and abs(cy - ct) <= hs:
            return _DRAG_T
        if cl - hs <= cx <= cr + hs and abs(cy - cb) <= hs:
            return _DRAG_B
        if ct - hs <= cy <= cb + hs and abs(cx - cl) <= hs:
            return _DRAG_I
        if ct - hs <= cy <= cb + hs and abs(cx - cr) <= hs:
            return _DRAG_O
        # 内部
        if cl <= cx <= cr and ct <= cy <= cb:
            return _DRAG_MOVE
        return _DRAG_NONE

    def _apply_drag(
        self,
        mode: int,
        L: int, T: int, R: int, B: int,
        dx: int, dy: int,
        event,
    ) -> tuple[int, int, int, int]:
        """根据拖拽模式应用位移，返回新 rect。"""
        if mode == _DRAG_MOVE:
            return L + dx, T + dy, R + dx, B + dy
        if mode == _DRAG_T:
            return L, T + dy, R, B
        if mode == _DRAG_B:
            return L, T, R, B + dy
        if mode == _DRAG_I:
            return L + dx, T, R, B
        if mode == _DRAG_O:
            return L, T, R + dx, B
        if mode == _DRAG_TL:
            return L + dx, T + dy, R, B
        if mode == _DRAG_TR:
            return L, T + dy, R + dx, B
        if mode == _DRAG_BL:
            return L + dx, T, R, B + dy
        if mode == _DRAG_BR:
            return L, T, R + dx, B + dy
        return L, T, R, B

    def _clamp_rect(
        self, rect: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        """clamp 到 [0, W] × [0, H] + 最小尺寸。"""
        L, T, R, B = rect
        W, H = self._raw_w, self._raw_h
        L = max(0, min(L, W - 1))
        R = max(L + 1, min(R, W))
        T = max(0, min(T, H - 1))
        B = max(T + 1, min(B, H))
        # 最小尺寸
        if R - L < self.MIN_RECT_SIZE:
            return self._rect  # 不动
        if B - T < self.MIN_RECT_SIZE:
            return self._rect
        return L, T, R, B

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------

    def _draw_image(self) -> None:
        if self._disp_w == self._raw_w and self._disp_h == self._raw_h:
            disp = self._raw_image
        else:
            disp = self._raw_image.resize(
                (self._disp_w, self._disp_h), Image.Resampling.LANCZOS
            )
        self._photo = ImageTk.PhotoImage(disp)
        self._image_item = self.create_image(0, 0, image=self._photo, anchor="nw")

    def _render_rect(self) -> None:
        # 删旧的
        for it in self._rect_items:
            self.delete(it)
        for it in self._handle_items:
            self.delete(it)
        self._rect_items.clear()
        self._handle_items.clear()

        L, T, R, B = self._rect
        cl = int(L * self._scale)
        ct = int(T * self._scale)
        cr = int(R * self._scale)
        cb = int(B * self._scale)

        # 4 边
        self._rect_items.append(
            self.create_line(cl, ct, cr, ct, fill=_EDGE_COLOR_TB, width=2, tags="edge_t")
        )
        self._rect_items.append(
            self.create_line(cl, cb, cr, cb, fill=_EDGE_COLOR_TB, width=2, tags="edge_b")
        )
        self._rect_items.append(
            self.create_line(cl, ct, cl, cb, fill=_EDGE_COLOR_IO, width=2, tags="edge_i")
        )
        self._rect_items.append(
            self.create_line(cr, ct, cr, cb, fill=_EDGE_COLOR_IO, width=2, tags="edge_o")
        )

        # 8 handles（4 角 + 4 边中点）
        hs = _HANDLE_SIZE
        handles = [
            (cl, ct),                       # TL
            (cr, ct),                       # TR
            (cl, cb),                       # BL
            (cr, cb),                       # BR
            ((cl + cr) // 2, ct),           # T
            ((cl + cr) // 2, cb),           # B
            (cl, (ct + cb) // 2),           # I
            (cr, (ct + cb) // 2),           # O
        ]
        for hx, hy in handles:
            self._handle_items.append(
                self.create_rectangle(
                    hx - hs, hy - hs, hx + hs, hy + hs,
                    fill=_HANDLE_COLOR, outline="black", width=1,
                    tags="handle",
                )
            )

        # 绑定事件（每次重新画完后确保）
        self.tag_bind("edge_t", "<ButtonPress-1>", self._on_press)
        self.tag_bind("edge_t", "<B1-Motion>", self._on_drag)
        # 简化：所有 tag 都绑相同事件
        for tag in ("edge_b", "edge_i", "edge_o", "handle"):
            self.tag_bind(tag, "<ButtonPress-1>", self._on_press)
            self.tag_bind(tag, "<B1-Motion>", self._on_drag)
        # 框内/全图：也绑定（平移）
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double_click)

    def _notify_change(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change(self.get_profile())
            except Exception:
                pass
