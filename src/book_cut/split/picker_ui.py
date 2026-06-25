"""v2.4 手动切分线 GUI 选择器。

提供 ``SplitLinePicker`` —— 在 ``tk.Toplevel`` 弹窗中展示一张代表页（PDF 首页或图片），
用户鼠标拖一条**竖直线**作为切分线；松开后调用方读 ``picker.profile`` 拿
``ManualSplitProfile``（含 ``split_x``、``source_size``、``deskew_applied`` 等）。

设计目标：
- 选择数学与 GUI 解耦（``SplitLineCanvas`` 仅负责渲染 + 鼠标事件）
- 大图 downscale 到 ``max_display`` 像素内显示，但 split_x 保留原图坐标系
- 支持双击重置（线回到图像中心）、Enter/Esc 快捷键（确认/取消）
- 状态变化通过 ``on_change`` 回调实时通知父窗（更新 ``manual_split_x_var``）

Why per-book profile 而不是 per-page：
v2.4 方案 A（决定 D2）—— 整本书一条线。代表页（PDF 首页 / 用户指定图）画的线
用于全书同一本古籍；古籍装订后左右页物理位置固定，不必每页选线。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageTk

from book_cut.split.manual import ManualSplitProfile

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:  # pragma: no cover — tkinter 不可用时 import 仍可成功
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]


# 视觉常量
_LINE_COLOR = "#d62728"      # 切分线（红）
_LINE_WIDTH = 2              # 线宽（canvas 像素）
_HANDLE_COLOR = "#ff7f0e"    # 拖动 handle（橙）
_HANDLE_SIZE = 12            # handle 半径（canvas 像素）
_GHOST_LINE_COLOR = "#888"   # 拖动前的辅助线（灰）
_GHOST_STIPPLE = "gray50"


class SplitLineCanvas(tk.Canvas):  # type: ignore[misc, valid-type]
    """可拖拽竖直切分线 Canvas（v2.4+）。

    Args:
        parent: 父 widget。
        image: 原始图像（PIL.Image）。
        split_x: 初始切分 x 坐标（原图坐标系）。
        on_change: split_x 变化时回调（接收新 x 坐标）。
        max_display: 显示区域最大边长（像素）；原图按此 downscale。
    """

    def __init__(
        self,
        parent,
        image: Image.Image,
        split_x: int | None = None,
        on_change: Callable[[int], None] | None = None,
        max_display: int = 1400,
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
            cursor="crosshair",
            **kwargs,
        )

        self._on_change = on_change
        self._split_x = split_x if split_x is not None else self._raw_w // 2
        self._drag_offset_x = 0  # 拖动时记录鼠标相对线中心的偏移

        self._photo = ImageTk.PhotoImage(self._raw_image.resize(
            (self._disp_w, self._disp_h),
            Image.Resampling.LANCZOS,
        ))
        self._draw_image()
        self._draw_line()

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double_click)
        self.bind("<Return>", lambda _: self._notify_change())

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def get_split_x(self) -> int:
        """返回当前切分线 x（原图坐标系，1 ≤ x < W）。"""
        return self._split_x

    def set_split_x(self, x: int) -> None:
        """设置切分线 x（原图坐标系），触发重绘。"""
        x = max(1, min(self._raw_w - 1, int(x)))
        if x != self._split_x:
            self._split_x = x
            self._redraw()

    def get_scale(self) -> float:
        return self._scale

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    def _on_press(self, event) -> None:
        cx = self.canvasx(event.x)
        # 命中线附近 → 拖动
        disp_x = self._split_x * self._scale
        if abs(cx - disp_x) <= _HANDLE_SIZE:
            self._drag_offset_x = cx - disp_x
            self.config(cursor="sb_h_double_arrow")
        else:
            # 否则视为在线上"重新落点"
            self._drag_offset_x = 0
            self._update_from_canvas(cx)

    def _on_drag(self, event) -> None:
        cx = self.canvasx(event.x)
        new_disp_x = cx - self._drag_offset_x
        new_x = int(new_disp_x / self._scale)
        self.set_split_x(new_x)

    def _on_release(self, _event) -> None:
        self.config(cursor="crosshair")
        self._notify_change()

    def _on_double_click(self, _event) -> None:
        # 双击重置到图像中心
        self.set_split_x(self._raw_w // 2)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _update_from_canvas(self, cx: int) -> None:
        new_x = int(cx / self._scale)
        self.set_split_x(new_x)

    def _draw_image(self) -> None:
        self.create_image(0, 0, image=self._photo, anchor="nw", tags="image")

    def _draw_line(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        # 清掉旧线（保留 image）
        self.delete("line", "handle")
        disp_x = self._split_x * self._scale
        self.create_line(
            disp_x, 0, disp_x, self._disp_h,
            fill=_LINE_COLOR, width=_LINE_WIDTH,
            tags="line",
        )
        # 把手（圆点）
        r = _HANDLE_SIZE // 2
        self.create_oval(
            disp_x - r, self._disp_h // 2 - r,
            disp_x + r, self._disp_h // 2 + r,
            fill=_HANDLE_COLOR, outline="black",
            tags="handle",
        )

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change(self._split_x)


# ----------------------------------------------------------------------------
# Toplevel 弹窗
# ----------------------------------------------------------------------------


class SplitLinePicker(tk.Toplevel):  # type: ignore[misc, valid-type]
    """手动切分线选择弹窗（v2.4+）。

    使用流程：
    1. 主窗「选切分线...」按钮 → ``open_split_picker(...)``
    2. 弹窗显示代表页（PDF 首页或图片），用户拖一条竖直线
    3. 点「确定」→ 把 ``ManualSplitProfile`` 写回 ``manual_split_x_var`` /
       ``manual_split_preset_var``（如指定了输出路径）
    4. 点「取消」→ 弹窗关闭，状态不变

    Args:
        parent: 父 widget。
        image: 代表页图像（PDF 渲染后或原始图片）。
        image_path: 代表页原始路径（展示用）。
        deskew_applied: 与 ``run_pipeline.args.deskew`` 一致；
            ``profile.deskew_applied`` 会用这个值，触发 MS009 校验。
        initial_profile: 可选初始 profile（用于"加载 preset"模式二次编辑）。
        output_path: 可选 JSON 输出路径；点「确定」自动写入。
        on_confirm: 可选回调 ``(profile: ManualSplitProfile) -> None``；
            若 None 且未给 output_path，仅返回 profile 不写盘。
    """

    def __init__(
        self,
        parent,
        image: Image.Image,
        image_path: Path | str,
        deskew_applied: bool = False,
        initial_profile: ManualSplitProfile | None = None,
        output_path: Path | str | None = None,
        on_confirm: Callable[[ManualSplitProfile], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(f"选切分线 · {Path(image_path).name}")
        self.transient(parent)
        self.grab_set()

        self._deskew_applied = deskew_applied
        self._output_path = Path(output_path) if output_path is not None else None
        self._on_confirm = on_confirm
        self._result: ManualSplitProfile | None = None

        # 主容器
        main = ttk.Frame(self, padding=8)
        main.pack(fill="both", expand=True)

        # 顶部提示
        ttk.Label(
            main,
            text="拖动竖直线到中缝位置（双击重置到中心；Enter 确认；Esc 取消）",
            foreground="#444",
        ).pack(fill="x", pady=(0, 6))

        # Canvas（带滚动条）
        canvas_frame = ttk.Frame(main)
        canvas_frame.pack(fill="both", expand=True)

        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical")
        v_scroll.pack(side="right", fill="y")

        initial_x = initial_profile.split_x if initial_profile is not None else None
        self._canvas = SplitLineCanvas(
            canvas_frame,
            image=image,
            split_x=initial_x,
            on_change=self._on_canvas_change,
        )
        self._canvas.pack(side="left", fill="both", expand=True)
        h_scroll.config(command=self._canvas.xview)
        v_scroll.config(command=self._canvas.yview)
        self._canvas.config(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        # 底部状态 + 按钮
        bottom = ttk.Frame(main)
        bottom.pack(fill="x", pady=(8, 0))

        self._status_var = tk.StringVar(value=self._make_status_text())
        ttk.Label(bottom, textvariable=self._status_var).pack(side="left")

        btn_frame = ttk.Frame(bottom)
        btn_frame.pack(side="right")
        ttk.Button(btn_frame, text="取消", command=self._on_cancel).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="确定", command=self._on_ok).pack(side="right")

        # 快捷键
        self.bind("<Escape>", lambda _: self._on_cancel())
        self.bind("<Return>", lambda _: self._on_ok())

        # 模态
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_visibility()
        self.focus_set()

    # ------------------------------------------------------------------
    # 状态显示
    # ------------------------------------------------------------------

    def _make_status_text(self) -> str:
        x = self._canvas.get_split_x()
        w, h = self._raw_size()
        return (
            f"split_x = {x} / {w}（原图坐标系）  ·  "
            f"左页宽 = {x}px，右页宽 = {w - x}px  ·  "
            f"deskew_applied = {self._deskew_applied}"
        )

    def _raw_size(self) -> tuple[int, int]:
        # 优先用 image 实际尺寸
        return self._canvas._raw_w, self._canvas._raw_h  # noqa: SLF001

    def _on_canvas_change(self, _x: int) -> None:
        self._status_var.set(self._make_status_text())

    # ------------------------------------------------------------------
    # 确认 / 取消
    # ------------------------------------------------------------------

    def _on_ok(self) -> None:
        x = self._canvas.get_split_x()
        w, h = self._raw_size()
        profile = ManualSplitProfile(
            split_x=x,
            source_size=(w, h),
            page=1,
            deskew_applied=self._deskew_applied,
            notes=f"选自 {Path(self._canvas._raw_image.filename).name if hasattr(self._canvas._raw_image, 'filename') else 'unknown'}",  # noqa: SLF001
        )
        self._result = profile

        # 写盘（如指定 output_path）
        if self._output_path is not None:
            try:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                self._output_path.write_text(profile.to_json(), encoding="utf-8")
            except OSError as e:
                tk.messagebox.showerror(
                    "保存失败",
                    f"无法写入 {self._output_path}: {e}",
                    parent=self,
                )
                return

        if self._on_confirm is not None:
            self._on_confirm(profile)

        self.grab_release()
        self.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.grab_release()
        self.destroy()

    def show(self) -> ManualSplitProfile | None:
        """阻塞直到弹窗关闭，返回 profile（取消则为 None）。"""
        self.wait_window()
        return self._result
