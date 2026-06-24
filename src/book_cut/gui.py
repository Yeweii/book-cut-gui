"""Tkinter GUI 主窗口。"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image

from book_cut import __version__
from book_cut.detect.manual import (
    ManualCropProfile,
)
from book_cut.gui_canvas import CropCanvas
from book_cut.io.page_size import (
    PDF_PAGE_SIZE_CHOICES,
    PDF_PAGE_UNIT_CHOICES,
)
from book_cut.pipeline import run_pipeline

# v1.4：GUI 用中文显示，映射到 CLI 的 ltr/rtl 值
PAGE_ORDER_LABELS: tuple[str, ...] = ("先左后右", "先右后左")
PAGE_ORDER_MAP: dict[str, str] = {"先左后右": "ltr", "先右后左": "rtl"}

# v1.7：PDF 页面统一尺寸（GUI 显示用中文，CLI 用 token）
PDF_PAGE_SIZE_LABELS: tuple[str, ...] = (
    "保持原图",
    "取最大",
    "首页尺寸",
    "A4",
    "A5",
    "Letter",
    "Legal",
    "自定义",
)
PDF_PAGE_SIZE_MAP: dict[str, str] = dict(zip(PDF_PAGE_SIZE_LABELS, PDF_PAGE_SIZE_CHOICES, strict=True))

# 单位下拉（中文显示 → CLI token）
PDF_PAGE_UNIT_LABELS: tuple[str, ...] = ("毫米 (mm)", "厘米 (cm)", "英寸 (inch)", "像素 (px)")
PDF_PAGE_UNIT_MAP: dict[str, str] = dict(zip(PDF_PAGE_UNIT_LABELS, PDF_PAGE_UNIT_CHOICES, strict=True))
PDF_PAGE_UNIT_REVERSE_MAP: dict[str, str] = {v: k for k, v in PDF_PAGE_UNIT_MAP.items()}

# v1.9+：preprocess 质量档（中文显示 → CLI token）
PREPROCESS_QUALITY_LABELS: tuple[str, ...] = ("快速", "平衡", "最佳")
PREPROCESS_QUALITY_MAP: dict[str, str] = dict(
    zip(PREPROCESS_QUALITY_LABELS, ("fast", "balanced", "best"), strict=True)
)


# ----------------------------------------------------------------------------
# v1.9+：简易 Tooltip（hover 显示提示文本）
# ----------------------------------------------------------------------------


class Tooltip:
    """tkinter 简易 tooltip：hover 显示说明文本。

    v1.9+：用于"图像增强"控件（每个 op 复选框 / 参数 / 质量下拉都有提示）。
    """

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        # 点击时也隐藏（避免 tooltip 遮住下拉）
        widget.bind("<ButtonPress>", self._hide)

    def _show(self, event: object = None) -> None:
        if self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 24
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            ttk.Label(
                self.tip,
                text=self.text,
                background="#ffffe0",
                relief="solid",
                borderwidth=1,
                padding=(6, 4),
                font=("Helvetica", 9),
                justify="left",
                wraplength=320,
            ).pack()
        except tk.TclError:
            self.tip = None

    def _hide(self, event: object = None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


# ----------------------------------------------------------------------------
# v1.6+ E1+E3：UI 联动 + 友好错误提示（无 Tk 依赖的纯函数，方便单测）
# ----------------------------------------------------------------------------


def _suggest_output_dir(input_path: str) -> str | None:
    """根据输入路径建议输出目录（E1b）。

    规则：
    - 空 / 不存在 → ``None``（调用方不改动 output）
    - 文件 → ``{parent}/{stem}_out``
    - 目录 → ``{parent}/{name}_out``

    调用方应在 ``output_var`` 为空时才填充，避免覆盖用户手动设置。
    """
    if not input_path:
        return None
    p = Path(input_path)
    if not p.exists():
        return None
    if p.is_file():
        return str(p.parent / f"{p.stem}_out")
    return str(p.parent / f"{p.name}_out")


# E3：常见异常 → 中文友好提示（原始 exc 作为 hint 附后）
_FRIENDLY_ERRORS: tuple[tuple[type, str], ...] = (
    (FileNotFoundError, "❌ 找不到文件，请检查输入路径是否正确"),
    (NotADirectoryError, "❌ 路径不是目录（输出目录必须是目录）"),
    (IsADirectoryError, "❌ 路径是目录而非文件"),
    (PermissionError, "❌ 没有访问权限，请检查文件/目录权限或是否被其他程序占用"),
)


def _format_error(exc: BaseException) -> str:
    """把异常转成中文友好提示（E3）。

    已知异常 → 命中映射表，原始信息作为 hint 附后（用户可调试）。
    未知异常 → 通用兜底 + 原始 ``type: message``。
    """
    for exc_type, hint in _FRIENDLY_ERRORS:
        if isinstance(exc, exc_type):
            return f"{hint}\n\n详细信息：{type(exc).__name__}: {exc}"
    return f"❌ 处理出错\n\n详细信息：{type(exc).__name__}: {exc}"


# ----------------------------------------------------------------------------
# 后台 worker
# ----------------------------------------------------------------------------


class _QueueWriter:
    """把 stdout/stderr 写入 queue，供 GUI 显示。"""

    def __init__(self, q: queue.Queue, tag: str) -> None:
        self._q = q
        self._tag = tag

    def write(self, msg: str) -> None:
        if msg and not msg.isspace():
            self._q.put((self._tag, msg.rstrip()))

    def flush(self) -> None:
        pass


def _run_pipeline_thread(
    input_path: Path,
    output_path: Path,
    values: dict,
    log_queue: queue.Queue,
    cancel_event: threading.Event,
) -> None:
    """在线程中跑 pipeline；日志通过 queue 推到主线程。"""
    args = argparse.Namespace(input=str(input_path), output=str(output_path), **values)

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _QueueWriter(log_queue, "log")
    sys.stderr = _QueueWriter(log_queue, "log")
    try:
        run_pipeline(args, cancel_event=cancel_event)
        if cancel_event.is_set():
            log_queue.put(("done", "⏹ 已停止"))
        else:
            log_queue.put(("done", "✅ 处理完成"))
    except Exception as e:  # noqa: BLE001
        log_queue.put(("error", _format_error(e)))
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# ----------------------------------------------------------------------------
# v2.2.2+：纯函数 — profile → 4 个 IntVar（拖框 Toplevel 应用按钮用）
# ----------------------------------------------------------------------------


def apply_profile_to_vars(
    profile: ManualCropProfile,
    top_var: tk.IntVar,
    bottom_var: tk.IntVar,
    inner_var: tk.IntVar,
    outer_var: tk.IntVar,
    mirror_var: tk.BooleanVar,
) -> None:
    """把 ManualCropProfile 的字段写到 4 个 IntVar + 1 个 BoolVar。

    v2.2.2+ 抽出来的纯函数（无 Tk widget 创建），便于单测：
    拖框 Toplevel"应用"按钮 → 读 canvas.get_profile() → apply_profile_to_vars。
    """
    top_var.set(profile.top)
    bottom_var.set(profile.bottom)
    inner_var.set(profile.inner)
    outer_var.set(profile.outer)
    mirror_var.set(profile.mirror_even)


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------


def run_gui() -> None:
    root = tk.Tk()
    root.title(f"古籍双页切分工具 v{__version__}")
    root.geometry("980x720")
    root.minsize(820, 600)

    # ---- 状态变量 ----
    input_var = tk.StringVar()
    output_var = tk.StringVar()
    split_var = tk.StringVar(value="gutter")
    crop_var = tk.StringVar(value="none")
    binarize_var = tk.StringVar(value="none")
    format_var = tk.StringVar(value="png")
    pdf_var = tk.BooleanVar(value=False)
    deskew_var = tk.BooleanVar(value=False)
    running_var = tk.BooleanVar(value=False)
    # v1.8+ dry-run
    dry_run_var = tk.BooleanVar(value=False)
    sample_n_var = tk.IntVar(value=3)
    preview_dir_var = tk.StringVar()  # 预览输出目录（空 = 系统 tmpdir）

    log_queue: queue.Queue = queue.Queue()

    # ---- 样式 ----
    style = ttk.Style()
    try:
        style.theme_use("aqua" if sys.platform == "darwin" else "clam")
    except tk.TclError:
        pass

    # ---- 布局 ----
    pad = {"padx": 8, "pady": 4}
    # 列权重：col0=标签固定宽度 / col1=内容扩展 / col2=按钮固定宽度
    root.columnconfigure(0, weight=0, minsize=70)
    root.columnconfigure(1, weight=1)
    root.columnconfigure(2, weight=0, minsize=120)

    # 标题
    ttk.Label(root, text="古籍双页切分工具", font=("Helvetica", 14, "bold")).grid(
        row=0, column=0, columnspan=3, pady=(12, 8)
    )

    # 输入
    ttk.Label(root, text="输入路径:").grid(row=1, column=0, sticky="e", **pad)
    ttk.Entry(root, textvariable=input_var).grid(row=1, column=1, sticky="ew", **pad)

    def browse_input() -> None:
        """统一选择 PDF / 图片文件 或 包含它们的文件夹（v2.2.5+）。

        原行为：先 askdirectory（选文件夹），取消后才 askopenfilename（选文件），
        2 步割裂。新行为：单 Toplevel 同时支持两种选择；用户也可直接输入路径。
        """
        win = tk.Toplevel(root)
        win.title("选择输入路径")
        win.geometry("520x180")
        win.transient(root)
        win.resizable(False, False)

        path_var = tk.StringVar(value=input_var.get())

        ttk.Label(
            win, text="选择 PDF / 图片文件，或包含它们的文件夹："
        ).pack(anchor="w", padx=12, pady=(12, 4))

        entry_frame = ttk.Frame(win)
        entry_frame.pack(fill="x", padx=12, pady=4)
        ttk.Entry(entry_frame, textvariable=path_var).pack(
            side="left", fill="x", expand=True
        )

        def _pick_file() -> None:
            p = filedialog.askopenfilename(
                parent=win,
                title="选择 PDF 或图片",
                filetypes=[
                    ("PDF", "*.pdf"),
                    ("图片", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"),
                    ("所有", "*.*"),
                ],
            )
            if p:
                path_var.set(p)

        def _pick_dir() -> None:
            p = filedialog.askdirectory(parent=win, title="选择文件夹")
            if p:
                path_var.set(p)

        def _confirm() -> None:
            p = path_var.get().strip()
            if p:
                input_var.set(p)
            win.destroy()

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=12, pady=(8, 4))
        ttk.Button(btn_row, text="选择文件…", command=_pick_file).pack(
            side="left", padx=2
        )
        ttk.Button(btn_row, text="选择文件夹…", command=_pick_dir).pack(
            side="left", padx=2
        )

        bottom_row = ttk.Frame(win)
        bottom_row.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(bottom_row, text="取消", command=win.destroy).pack(
            side="right", padx=2
        )
        ttk.Button(bottom_row, text="确定", command=_confirm).pack(
            side="right", padx=2
        )

        win.bind("<Return>", lambda _e: _confirm())
        win.bind("<Escape>", lambda _e: win.destroy())

    ttk.Button(root, text="浏览…", command=browse_input).grid(row=1, column=2, **pad)

    # v1.6+ E1b：input 变化时，若 output 为空则自动建议
    def _on_input_change(*_args: object) -> None:
        if output_var.get():
            return  # 用户已手动填 output，不覆盖
        suggested = _suggest_output_dir(input_var.get())
        if suggested:
            output_var.set(suggested)

    input_var.trace_add("write", _on_input_change)

    # 输出
    ttk.Label(root, text="输出目录:").grid(row=2, column=0, sticky="e", **pad)
    ttk.Entry(root, textvariable=output_var).grid(row=2, column=1, sticky="ew", **pad)

    def browse_output() -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            output_var.set(path)

    ttk.Button(root, text="浏览…", command=browse_output).grid(row=2, column=2, **pad)

    # 切分策略
    ttk.Label(root, text="预处理:").grid(row=3, column=0, sticky="e", **pad)
    pp_frame = ttk.Frame(root)
    pp_frame.grid(row=3, column=1, sticky="w", **pad)
    ttk.Checkbutton(pp_frame, text="倾斜校正（deskew）", variable=deskew_var).grid(
        row=0, column=0
    )

    ttk.Label(root, text="切分策略:").grid(row=4, column=0, sticky="e", **pad)
    split_frame = ttk.Frame(root)
    split_frame.grid(row=4, column=1, sticky="w", **pad)
    for i, (val, label) in enumerate(
        [("gutter", "中缝（推荐）"), ("border", "版框线"), ("half", "对半"), ("none", "不切分")]
    ):
        ttk.Radiobutton(split_frame, text=label, variable=split_var, value=val).grid(
            row=0, column=i, padx=4
        )

    # 裁切
    ttk.Label(root, text="单页裁切:").grid(row=5, column=0, sticky="e", **pad)
    crop_frame = ttk.Frame(root)
    crop_frame.grid(row=5, column=1, sticky="w", **pad)
    for i, (val, label) in enumerate(
        [("none", "不裁"), ("trim", "切白边"), ("border", "版框内裁"), ("manual", "手动（拖框）")]
    ):
        ttk.Radiobutton(crop_frame, text=label, variable=crop_var, value=val).grid(
            row=0, column=i, padx=4
        )
    # 自适应裁切：v1.3 新增
    crop_adaptive_var = tk.BooleanVar(value=True)
    paper_pages_var = tk.IntVar(value=5)
    paper_pages_spin = ttk.Spinbox(
        crop_frame,
        textvariable=paper_pages_var,
        from_=1,
        to=50,
        width=4,
    )

    def _on_adaptive_toggle(*_args) -> None:
        state = "normal" if crop_adaptive_var.get() else "disabled"
        paper_pages_spin.config(state=state)

    crop_adaptive_var.trace_add("write", _on_adaptive_toggle)
    ttk.Checkbutton(
        crop_frame,
        text="自适应（按纸色）",
        variable=crop_adaptive_var,
    ).grid(row=0, column=4, padx=(16, 4))
    ttk.Label(crop_frame, text="采样页:").grid(row=0, column=5)
    paper_pages_spin.grid(row=0, column=6, padx=(0, 4))

    # v1.6+ B线：抗杂质（默认开，对应 CLI ``--no-morph`` 反义）
    morph_var = tk.BooleanVar(value=True)
    morph_check = ttk.Checkbutton(
        crop_frame,
        text="抗杂质（形态学清尘点）",
        variable=morph_var,
    )
    morph_check.grid(row=1, column=0, columnspan=4, sticky="w", padx=(0, 4), pady=(4, 0))

    # v1.6+ E1a：crop=none 时抗杂质无意义，禁用 checkbox
    def _on_crop_change(*_args: object) -> None:
        morph_check.config(state="disabled" if crop_var.get() == "none" else "normal")
        # v2.2+：manual 模式启用 Manual Crop 面板
        manual_state = "normal" if crop_var.get() == "manual" else "disabled"
        for w in manual_widgets:
            try:
                w.config(state=manual_state)
            except tk.TclError:
                pass  # Combobox 等特殊控件可能没有 state
        # v2.2.1+：切到 manual 自动展开，方便用户编辑 padding
        if crop_var.get() == "manual" and not manual_expanded_var.get():
            _toggle_manual_expand()

    crop_var.trace_add("write", _on_crop_change)

    # v2.2+：Manual Crop 面板（拖框 + 4 个 padding + preset 加载/保存）
    # v2.2.1+：行号独立（不再与二值化撞 row=6），全中文 + 展开/收起按钮
    manual_frame = ttk.LabelFrame(root, text="手动裁切（v2.2+，替代自动裁切）")
    manual_frame.grid(row=6, column=0, columnspan=3, sticky="ew", **pad)

    # 展开/收起按钮（v2.2.1+）：默认展开；用户可折叠节省空间
    # 按钮始终可用（不在 _on_crop_change 的禁用列表中），方便用户在非 manual
    # 模式下也能展开看 padding 值
    manual_expanded_var = tk.BooleanVar(value=True)

    def _toggle_manual_expand() -> None:
        """切换 Manual Crop 内部子 frame 的可见性。"""
        new_state = not manual_expanded_var.get()
        manual_expanded_var.set(new_state)
        if new_state:
            manual_pad_frame.grid()
            manual_btn_frame.grid()
            manual_expand_btn.config(text="▼ 收起")
        else:
            manual_pad_frame.grid_remove()
            manual_btn_frame.grid_remove()
            manual_expand_btn.config(text="▶ 展开")

    manual_expand_btn = ttk.Button(
        manual_frame, text="▼ 收起", width=8, command=_toggle_manual_expand
    )
    manual_expand_btn.grid(row=0, column=2, sticky="e", padx=(0, 8), pady=(2, 0))

    # 4 个 padding（中缝 = inner / 外侧 = outer）
    manual_pad_frame = ttk.Frame(manual_frame)
    manual_pad_frame.grid(row=1, column=0, columnspan=3, sticky="w", **pad)
    ttk.Label(manual_pad_frame, text="上:").grid(row=0, column=0)
    manual_top_var = tk.IntVar(value=50)
    ttk.Spinbox(manual_pad_frame, from_=0, to=9999, width=6, textvariable=manual_top_var).grid(
        row=0, column=1, padx=(2, 8)
    )
    ttk.Label(manual_pad_frame, text="下:").grid(row=0, column=2)
    manual_bottom_var = tk.IntVar(value=40)
    ttk.Spinbox(manual_pad_frame, from_=0, to=9999, width=6, textvariable=manual_bottom_var).grid(
        row=0, column=3, padx=(2, 8)
    )
    ttk.Label(manual_pad_frame, text="中缝:").grid(row=0, column=4)
    manual_inner_var = tk.IntVar(value=80)
    ttk.Spinbox(manual_pad_frame, from_=0, to=9999, width=6, textvariable=manual_inner_var).grid(
        row=0, column=5, padx=(2, 8)
    )
    ttk.Label(manual_pad_frame, text="外侧:").grid(row=0, column=6)
    manual_outer_var = tk.IntVar(value=30)
    ttk.Spinbox(manual_pad_frame, from_=0, to=9999, width=6, textvariable=manual_outer_var).grid(
        row=0, column=7, padx=(2, 8)
    )

    # 镜像 + 预设按钮
    manual_btn_frame = ttk.Frame(manual_frame)
    manual_btn_frame.grid(row=2, column=0, columnspan=3, sticky="w", **pad)
    manual_mirror_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        manual_btn_frame, text="偶页自动镜像（中缝↔外侧）",
        variable=manual_mirror_var,
    ).grid(row=0, column=0, padx=(0, 16))

    def _save_manual_preset() -> None:
        path = filedialog.asksaveasfilename(
            title="保存手动裁切预设",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        prof = ManualCropProfile(
            top=manual_top_var.get(),
            bottom=manual_bottom_var.get(),
            inner=manual_inner_var.get(),
            outer=manual_outer_var.get(),
            mirror_even=manual_mirror_var.get(),
        )
        Path(path).write_text(prof.to_json())
        messagebox.showinfo("已保存", f"预设已保存到\n{path}")

    def _load_manual_preset() -> None:
        path = filedialog.askopenfilename(
            title="加载手动裁切预设",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            prof = ManualCropProfile.from_json(Path(path).read_text())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("加载失败", f"预设解析失败：\n{e}")
            return
        manual_top_var.set(prof.top)
        manual_bottom_var.set(prof.bottom)
        manual_inner_var.set(prof.inner)
        manual_outer_var.set(prof.outer)
        manual_mirror_var.set(prof.mirror_even)

    ttk.Button(manual_btn_frame, text="加载预设…", command=_load_manual_preset).grid(
        row=0, column=1, padx=4
    )
    ttk.Button(manual_btn_frame, text="保存预设…", command=_save_manual_preset).grid(
        row=0, column=2, padx=4
    )

    # v2.2.2+：选择样本页 → 弹 Toplevel 拖框 → 自动算 padding 写回 Spinbox
    def _open_sample_page() -> None:
        """选图片 → 弹拖框 Toplevel → 应用后更新 4 个 padding IntVar。"""
        path = filedialog.askopenfilename(
            title="选择样本页（用于拖框计算 padding）",
            filetypes=[
                ("图片", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"),
                ("PDF", "*.pdf"),
                ("所有", "*.*"),
            ],
        )
        if not path:
            return
        try:
            img = Image.open(path)
            if img.mode != "L":
                img = img.convert("L")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("加载失败", f"图片加载失败：\n{e}")
            return
        _show_sample_crop_window(img)

    def _show_sample_crop_window(img: Image.Image) -> None:
        """弹 Toplevel 显示图片 + CropCanvas，应用时回写 manual_*_var。"""
        win = tk.Toplevel(root)
        win.title("拖框计算 padding（双击重置；点击'应用'写回主窗口）")
        win.geometry("1000x860")  # v2.2.4+ 调高 40px 让底部"应用"按钮更稳

        # 顶部工具栏：奇/偶页 toggle + 当前样本尺寸
        toolbar = ttk.Frame(win)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)
        is_even_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(
            toolbar, text="奇页（inner=左，outer=右）", variable=is_even_var, value=False
        ).pack(side="left")
        ttk.Radiobutton(
            toolbar, text="偶页（inner=右，outer=左）", variable=is_even_var, value=True
        ).pack(side="left", padx=(8, 16))
        ttk.Label(
            toolbar, text=f"样本尺寸: {img.size[0]} × {img.size[1]}", foreground="gray"
        ).pack(side="left", padx=(16, 0))

        # 缩放按钮（v2.2.3+）：方便查看大图全貌 / 局部放大精确拖框
        zoom_label = ttk.Label(toolbar, text="缩放: ", foreground="gray")
        zoom_label.pack(side="left", padx=(24, 0))

        # 缩放比例显示（更新由 _update_zoom_label 维护）
        zoom_pct_var = tk.StringVar(value="100%")

        def _update_zoom_label() -> None:
            zoom_pct_var.set(f"{int(canvas.get_scale() * 100)}%")

        ttk.Button(toolbar, text="适应窗口", width=8, command=lambda: _on_fit()).pack(
            side="left", padx=(8, 2)
        )
        ttk.Button(toolbar, text="放大", width=6, command=lambda: _on_zoom_in()).pack(
            side="left", padx=2
        )
        ttk.Button(toolbar, text="缩小", width=6, command=lambda: _on_zoom_out()).pack(
            side="left", padx=2
        )
        # v2.2.4+ 移除"100%" 按钮（与右边百分比 label 重复，看起来像空白按钮）；
        # 实际大小（1.0）用"适应窗口"覆盖——想看原图大小就拉到 100% 也方便。
        ttk.Label(toolbar, textvariable=zoom_pct_var, foreground="gray", width=6).pack(
            side="left", padx=(4, 0)
        )

        # v2.2.6+ 把"应用"按钮搬到顶部 toolbar（v2.2.4 放底部 btn_frame
        # 在 1000x860 视口里被画布/任务栏挤出可见区，用户截图反馈看不到）。
        # 用 Separator + 较宽按钮让"应用"在工具栏右侧最醒目位置，恒可见。
        ttk.Separator(toolbar, orient="vertical").pack(
            side="right", fill="y", padx=(16, 4)
        )
        # lambda 推迟 _on_apply 解析（_on_apply 在函数下方定义）
        ttk.Button(
            toolbar, text="应用", width=8, command=lambda: _on_apply()
        ).pack(side="right", padx=4)

        # 初始 profile：从当前 manual_*_var 读（保留用户已设值）
        initial_profile = ManualCropProfile(
            top=manual_top_var.get(),
            bottom=manual_bottom_var.get(),
            inner=manual_inner_var.get(),
            outer=manual_outer_var.get(),
            mirror_even=manual_mirror_var.get(),
            source_size=img.size,
        )

        # Canvas 容器（含 Scrollbar）
        canvas_frame = ttk.Frame(win)
        canvas_frame.pack(side="top", fill="both", expand=True, padx=8, pady=4)
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        x_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal")
        x_scroll.pack(side="bottom", fill="x")
        canvas = CropCanvas(
            canvas_frame,
            img,
            profile=initial_profile,
            is_even=is_even_var.get(),
            mirror_even=manual_mirror_var.get(),
        )
        canvas.pack(side="left", fill="both", expand=True)
        canvas.config(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        y_scroll.config(command=canvas.yview)
        x_scroll.config(command=canvas.xview)

        # 缩放回调
        def _on_fit() -> None:
            # 用 canvas_frame 的当前 size 算 best fit（去掉 scrollbar 占的约 20px）
            win.update_idletasks()
            fw = max(100, canvas_frame.winfo_width() - 24)
            fh = max(100, canvas_frame.winfo_height() - 24)
            canvas.fit_to_size(max_w=fw, max_h=fh)
            _update_zoom_label()

        def _on_zoom_in() -> None:
            canvas.zoom_in()
            _update_zoom_label()

        def _on_zoom_out() -> None:
            canvas.zoom_out()
            _update_zoom_label()

        # 窗口首次布局完后自动 fit（避免大图底部被切）
        win.update_idletasks()
        win.after(50, _on_fit)

        # 奇/偶页 → canvas.set_is_even
        def _sync_is_even(*_a: object) -> None:
            canvas.set_is_even(is_even_var.get())

        is_even_var.trace_add("write", _sync_is_even)

        # 底部按钮（v2.2.4+ 加 Separator 让"应用"更醒目）
        ttk.Separator(win, orient="horizontal").pack(
            side="bottom", fill="x", padx=8, pady=(4, 0)
        )
        btn_frame = ttk.Frame(win)
        btn_frame.pack(side="bottom", fill="x", padx=8, pady=8)

        def _on_apply() -> None:
            prof = canvas.get_profile()
            apply_profile_to_vars(
                prof,
                manual_top_var,
                manual_bottom_var,
                manual_inner_var,
                manual_outer_var,
                manual_mirror_var,
            )
            win.destroy()

        ttk.Button(btn_frame, text="重置", command=canvas.reset).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="取消", command=win.destroy).pack(side="right", padx=4)
        # v2.2.6+ "应用" 按钮已搬到顶部 toolbar（更醒目 + 恒可见），
        # 底部 btn_frame 只留"重置"和"取消"。

        # 关窗时也清回调（避免 trace 引用悬空）
        win.bind(
            "<Destroy>",
            lambda _e: (is_even_var.trace_remove("write", _sync_is_even) if is_even_var.trace_info() else None),
        )

    ttk.Button(manual_btn_frame, text="选择样本页…", command=_open_sample_page).grid(
        row=0, column=3, padx=(12, 4)
    )

    # 用 conv 拿 manual 面板的子控件（用于 _on_crop_change 批量禁用）
    # 注意：manual_expand_btn 不在禁用列表里——用户任何时候都能展开/收起
    manual_widgets: list[tk.Widget] = []
    for child in manual_frame.winfo_children():
        if child is manual_expand_btn:
            continue  # 展开/收起按钮始终可用
        manual_widgets.append(child)
        for sub in child.winfo_children():
            manual_widgets.append(sub)
    _on_crop_change()  # 初始化时跑一次对齐默认状态（必须在 manual_widgets 之后）

    # 二值化（v2.2.1+：行号 +1 让出给 manual_frame）
    ttk.Label(root, text="二值化:").grid(row=7, column=0, sticky="e", **pad)
    bin_frame = ttk.Frame(root)
    bin_frame.grid(row=7, column=1, sticky="w", **pad)
    ttk.Combobox(
        bin_frame,
        textvariable=binarize_var,
        values=["none", "otsu", "adaptive", "sauvola"],
        state="readonly",
        width=14,
    ).grid(row=0, column=0)
    ttk.Label(bin_frame, text="（古籍推荐 sauvola）", foreground="gray").grid(
        row=0, column=1, padx=8
    )
    # v2.0+：1-bit 紧凑输出 checkbox（默认勾选；不勾选走 8-bit 兼容）
    binary_1bit_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        bin_frame,
        text="1-bit 紧凑输出（体积 8x 缩减）",
        variable=binary_1bit_var,
    ).grid(row=0, column=2, padx=8)

    # v1.8+ dry-run 控件
    dry_frame = ttk.Frame(root)
    dry_frame.grid(row=7, column=2, sticky="w", **pad)
    ttk.Checkbutton(
        dry_frame,
        text="Dry-run 预览（不写盘）",
        variable=dry_run_var,
    ).grid(row=0, column=0)
    ttk.Label(dry_frame, text="采样:").grid(row=0, column=1, padx=(8, 2))
    sample_n_spin = ttk.Spinbox(
        dry_frame,
        textvariable=sample_n_var,
        from_=1,
        to=20,
        width=4,
    )
    sample_n_spin.grid(row=0, column=2, padx=(0, 2))
    ttk.Label(dry_frame, text="页", foreground="gray").grid(row=0, column=3)

    # 输出格式 + PDF（v2.2.1+：行号 +1）
    ttk.Label(root, text="输出格式:").grid(row=8, column=0, sticky="e", **pad)
    fmt_frame = ttk.Frame(root)
    fmt_frame.grid(row=8, column=1, columnspan=2, sticky="ew", **pad)
    ttk.Combobox(
        fmt_frame,
        textvariable=format_var,
        values=["png", "jpg", "tif", "webp"],
        state="readonly",
        width=10,
    ).grid(row=0, column=0)
    ttk.Checkbutton(fmt_frame, text="同时输出 PDF", variable=pdf_var).grid(
        row=0, column=1, padx=12
    )

    # v1.4：页序 + 保留书签
    order_var = tk.StringVar(value=PAGE_ORDER_LABELS[0])
    outline_var = tk.BooleanVar(value=True)
    po_frame = ttk.Frame(fmt_frame)
    po_frame.grid(row=0, column=2, padx=(16, 0))
    ttk.Label(po_frame, text="页序:").grid(row=0, column=0)
    ttk.Combobox(
        po_frame,
        textvariable=order_var,
        values=list(PAGE_ORDER_LABELS),
        state="readonly",
        width=8,
    ).grid(row=0, column=1, padx=(2, 8))
    ttk.Checkbutton(po_frame, text="保留书签", variable=outline_var).grid(
        row=0, column=2
    )

    # v1.7：PDF 页面统一尺寸（放在 PDF 选项下一行）
    pps_frame = ttk.Frame(fmt_frame)
    pps_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ttk.Label(pps_frame, text="PDF 页面尺寸:").grid(row=0, column=0)
    pps_var = tk.StringVar(value=PDF_PAGE_SIZE_LABELS[0])
    pps_unit_var = tk.StringVar(value=PDF_PAGE_UNIT_LABELS[0])
    pps_w_var = tk.StringVar(value="280")
    pps_h_var = tk.StringVar(value="200")
    pps_combo = ttk.Combobox(
        pps_frame,
        textvariable=pps_var,
        values=list(PDF_PAGE_SIZE_LABELS),
        state="readonly",
        width=10,
    )
    pps_combo.grid(row=0, column=1, padx=(2, 8))
    ttk.Label(pps_frame, text="W:").grid(row=0, column=2)
    pps_w_entry = ttk.Entry(pps_frame, textvariable=pps_w_var, width=6)
    pps_w_entry.grid(row=0, column=3, padx=(2, 4))
    ttk.Label(pps_frame, text="H:").grid(row=0, column=4)
    pps_h_entry = ttk.Entry(pps_frame, textvariable=pps_h_var, width=6)
    pps_h_entry.grid(row=0, column=5, padx=(2, 4))
    pps_unit_combo = ttk.Combobox(
        pps_frame,
        textvariable=pps_unit_var,
        values=list(PDF_PAGE_UNIT_LABELS),
        state="readonly",
        width=10,
    )
    pps_unit_combo.grid(row=0, column=6, padx=(2, 0))

    # v1.9+：图像增强（中文选项 + 可调参数 + hover 工具提示）
    # 4 个 op 各自独立勾选 + 参数 Spinbox；chain 由勾选状态自动拼装
    sharpen_var = tk.BooleanVar(value=False)
    sharpen_amt_var = tk.DoubleVar(value=1.5)
    denoise_var = tk.BooleanVar(value=False)
    denoise_h_var = tk.DoubleVar(value=7.0)
    clahe_var = tk.BooleanVar(value=False)
    clahe_clip_var = tk.DoubleVar(value=2.0)
    gamma_var = tk.BooleanVar(value=False)
    gamma_value_var = tk.DoubleVar(value=1.2)
    preprocess_quality_var = tk.StringVar(value=PREPROCESS_QUALITY_LABELS[1])  # 平衡

    ttk.Label(fmt_frame, text="图像增强:").grid(
        row=2, column=0, sticky="nw", pady=(6, 0)
    )
    pre_inner = ttk.Frame(fmt_frame)
    pre_inner.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))

    # 行 0：4 个 op 复选框 + 各自参数 Spinbox
    sharpen_chk = ttk.Checkbutton(pre_inner, text="锐化", variable=sharpen_var)
    sharpen_chk.grid(row=0, column=0, sticky="w")
    ttk.Label(pre_inner, text="强度").grid(row=0, column=1, padx=(6, 2))
    sharpen_spin = ttk.Spinbox(
        pre_inner,
        textvariable=sharpen_amt_var,
        from_=0.5,
        to=3.0,
        increment=0.1,
        width=5,
    )
    sharpen_spin.grid(row=0, column=2)

    denoise_chk = ttk.Checkbutton(pre_inner, text="降噪", variable=denoise_var)
    denoise_chk.grid(row=0, column=3, padx=(14, 0), sticky="w")
    ttk.Label(pre_inner, text="h").grid(row=0, column=4, padx=(6, 2))
    denoise_spin = ttk.Spinbox(
        pre_inner,
        textvariable=denoise_h_var,
        from_=1.0,
        to=15.0,
        increment=0.5,
        width=5,
    )
    denoise_spin.grid(row=0, column=5)

    clahe_chk = ttk.Checkbutton(pre_inner, text="对比度增强", variable=clahe_var)
    clahe_chk.grid(row=0, column=6, padx=(14, 0), sticky="w")
    ttk.Label(pre_inner, text="clip").grid(row=0, column=7, padx=(6, 2))
    clahe_spin = ttk.Spinbox(
        pre_inner,
        textvariable=clahe_clip_var,
        from_=0.5,
        to=5.0,
        increment=0.1,
        width=5,
    )
    clahe_spin.grid(row=0, column=8)

    gamma_chk = ttk.Checkbutton(pre_inner, text="伽马校正", variable=gamma_var)
    gamma_chk.grid(row=0, column=9, padx=(14, 0), sticky="w")
    ttk.Label(pre_inner, text="γ").grid(row=0, column=10, padx=(6, 2))
    gamma_spin = ttk.Spinbox(
        pre_inner,
        textvariable=gamma_value_var,
        from_=0.3,
        to=3.0,
        increment=0.05,
        width=5,
    )
    gamma_spin.grid(row=0, column=11)

    # 行 1：质量下拉 + 恢复默认 + 操作提示
    ttk.Label(pre_inner, text="质量:").grid(row=1, column=0, sticky="e", pady=(4, 0))
    quality_combo = ttk.Combobox(
        pre_inner,
        textvariable=preprocess_quality_var,
        values=PREPROCESS_QUALITY_LABELS,
        state="readonly",
        width=8,
    )
    quality_combo.grid(row=1, column=1, sticky="w", pady=(4, 0))

    def _reset_preprocess() -> None:
        sharpen_var.set(False)
        sharpen_amt_var.set(1.5)
        denoise_var.set(False)
        denoise_h_var.set(7.0)
        clahe_var.set(False)
        clahe_clip_var.set(2.0)
        gamma_var.set(False)
        gamma_value_var.set(1.2)
        preprocess_quality_var.set(PREPROCESS_QUALITY_LABELS[1])

    ttk.Button(pre_inner, text="恢复默认", command=_reset_preprocess).grid(
        row=1, column=2, columnspan=2, sticky="w", padx=(8, 0), pady=(4, 0)
    )
    ttk.Label(
        pre_inner,
        text="勾选启用操作，调节数值覆盖默认（鼠标悬停看提示）",
        foreground="gray",
    ).grid(
        row=1, column=4, columnspan=8, sticky="w", padx=(8, 0), pady=(4, 0)
    )

    # 工具提示：每个控件都说明"推荐场景 / 参数范围 / 默认值"
    Tooltip(
        sharpen_chk,
        "锐化文字边缘，让模糊的墨迹变清晰\n"
        "算法：Unsharp Mask（原图 + amount × (原图 − 高斯)）\n"
        "推荐：古籍模糊 / 扫描失焦",
    )
    Tooltip(
        sharpen_spin,
        "锐化强度\n"
        "范围 0.5 – 3.0，默认 1.5（平衡档）\n"
        "越大越锐利，过大易失真/振铃",
    )
    Tooltip(
        denoise_chk,
        "去除扫描噪点和纸张污渍\n"
        "算法：快速=高斯模糊 / 平衡=双边滤波（边缘保留） / 最佳=NL-Means\n"
        "推荐：古籍泛黄 / 有杂点 / 暗房扫描",
    )
    Tooltip(
        denoise_spin,
        "降噪强度 h\n"
        "平衡档 = 双边滤波 σ（默认 7）\n"
        "最佳档 = NL-Means h（默认 10）\n"
        "范围 1 – 15，越大去噪越强",
    )
    Tooltip(
        clahe_chk,
        "局部直方图均衡化（CLAHE）\n"
        "改善光照不均 / 局部明暗不一致 / 暗角\n"
        "推荐：扫描时光照不均 / 古籍边缘发暗",
    )
    Tooltip(
        clahe_spin,
        "对比度限制 clipLimit\n"
        "范围 0.5 – 5.0，默认 2.0\n"
        "越大对比越强，过大易放大噪点",
    )
    Tooltip(
        gamma_chk,
        "伽马校正（幂律变换）\n"
        "γ < 1 提亮，γ > 1 压暗\n"
        "推荐：整体偏暗 / 偏亮的扫描件",
    )
    Tooltip(
        gamma_spin,
        "伽马值 γ\n"
        "范围 0.3 – 3.0，默认 1.2\n"
        "古籍深底场景 1.2；偏暗用 <1；偏亮用 >1\n"
        "内部 clamp 到 [0.25, 4.0]",
    )
    Tooltip(
        quality_combo,
        "后端算法选择\n"
        "快速 = PIL 内置（最快，质量一般）\n"
        "平衡 = 双边滤波（默认，推荐古籍）\n"
        "最佳 = NL-Means（慢 5x，效果最好）",
    )

    def _on_pps_change(*_args: object) -> None:
        """PDF 页面尺寸下拉变化：custom 启用 W/H/unit，其他禁用。"""
        is_custom = pps_var.get() == "自定义"
        state_w = "normal" if is_custom else "disabled"
        pps_w_entry.config(state=state_w)
        pps_h_entry.config(state=state_w)
        pps_unit_combo.config(state="readonly" if is_custom else "disabled")

    pps_var.trace_add("write", _on_pps_change)
    _on_pps_change()  # 初始化时对齐默认状态

    # v1.7：PDF 未勾选时整行禁用（与 PDF 配套）
    def _on_pdf_change(*_args: object) -> None:
        pps_combo.config(state="readonly" if pdf_var.get() else "disabled")
        # W/H/unit 由 _on_pps_change 控制，仅在 PDF 勾选时才有意义
        if not pdf_var.get():
            pps_w_entry.config(state="disabled")
            pps_h_entry.config(state="disabled")
            pps_unit_combo.config(state="disabled")
        else:
            _on_pps_change()  # 重新触发按 custom/non-custom 切换

    pdf_var.trace_add("write", _on_pdf_change)
    _on_pdf_change()  # 初始化时跑一次对齐默认状态

    # v1.8+ dry-run：勾选时整张"输出格式"行 disable
    def _set_fmt_state_recursive(parent, state: str) -> None:
        """递归设置 fmt_frame 子树的 state。"""
        for w in parent.winfo_children():
            try:
                cls = w.winfo_class()
                if cls in ("TCombobox", "TEntry"):
                    w.config(state=state if state == "disabled" else "readonly")
                elif cls in ("TCheckbutton", "TRadiobutton"):
                    # checkbutton 没法直接 disable，存 state 但点击仍响应
                    # 这里只把视觉灰度变一下：用户勾选 dry-run 时 PDF/output 等无意义
                    pass
            except tk.TclError:
                pass
            # 递归进子容器（po_frame / pps_frame）
            if w.winfo_children():
                _set_fmt_state_recursive(w, state)

    def _on_dry_run_change(*_args: object) -> None:
        if dry_run_var.get():
            _set_fmt_state_recursive(fmt_frame, "disabled")
        else:
            # 恢复时触发 PDF 联动（让 pps 等回到正确 state）
            _on_pdf_change()
            _on_pps_change()

    dry_run_var.trace_add("write", _on_dry_run_change)

    # 进度条（v2.2.1+：行号 +1 让出给 manual_frame）
    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.grid(row=9, column=0, columnspan=3, sticky="ew", padx=8, pady=(12, 4))

    # v1.8.1+ cancel event：每次 on_run 新建一个，透传给 pipeline thread
    cancel_event_holder: list[threading.Event | None] = [None]

    # 执行按钮
    def _build_preprocess_chain() -> str:
        """v1.9+：从 4 个 op 复选框 + 参数 Spinbox 自动拼装 chain。

        顺序：sharpen → denoise → clahe → gamma（前一个的输出是后一个的输入）。
        全部未勾选 → 空字符串 → dispatcher 跳过。
        """
        tokens: list[str] = []
        if sharpen_var.get():
            tokens.append(f"sharpen={sharpen_amt_var.get():g}")
        if denoise_var.get():
            tokens.append(f"denoise={denoise_h_var.get():g}")
        if clahe_var.get():
            tokens.append(f"clahe={clahe_clip_var.get():g}")
        if gamma_var.get():
            tokens.append(f"gamma={gamma_value_var.get():g}")
        return ",".join(tokens)

    def on_run() -> None:
        if not input_var.get() or not output_var.get():
            messagebox.showwarning("提示", "请先填写输入路径和输出目录")
            return
        if running_var.get():
            return

        log_text.configure(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.configure(state="disabled")
        running_var.set(True)
        run_btn.config(state="disabled")
        stop_btn.config(state="normal")
        progress.start(80)
        # 新建 cancel event
        cancel_event_holder[0] = threading.Event()

        values = {
            "split": split_var.get(),
            "crop": crop_var.get(),
            "crop_adaptive": "auto" if crop_adaptive_var.get() else "fixed",
            "paper_pages": paper_pages_var.get(),
            "binarize": binarize_var.get(),
            "binary_mode": "1bit" if binary_1bit_var.get() else "8bit",
            "format": format_var.get(),
            "pdf": pdf_var.get(),
            "deskew": deskew_var.get(),
            "page_order": PAGE_ORDER_MAP[order_var.get()],
            "outline": outline_var.get(),
            "no_morph": not morph_var.get(),
            # v1.7：PDF 页面统一尺寸
            "pdf_page_size": PDF_PAGE_SIZE_MAP[pps_var.get()],
            "pdf_page_dim": f"{pps_w_var.get()}x{pps_h_var.get()}",
            "pdf_page_unit": PDF_PAGE_UNIT_MAP[pps_unit_var.get()],
            # v1.8+ dry-run
            "dry_run": dry_run_var.get(),
            "sample_n": sample_n_var.get(),
            "preview_output": preview_dir_var.get() or None,
            # v1.9+：图片预处理增强（chain 由勾选状态自动拼装）
            "preprocess": _build_preprocess_chain(),
            "preprocess_quality": PREPROCESS_QUALITY_MAP[preprocess_quality_var.get()],
            # v2.2+：manual crop
            "manual_odd_padding": (
                f"T={manual_top_var.get()},B={manual_bottom_var.get()},"
                f"I={manual_inner_var.get()},O={manual_outer_var.get()}"
            ) if crop_var.get() == "manual" else None,
            "manual_mirror_even": manual_mirror_var.get(),
            "manual_preset": None,
            "manual_save_preset": None,
        }
        t = threading.Thread(
            target=_run_pipeline_thread,
            args=(
                Path(input_var.get()),
                Path(output_var.get()),
                values,
                log_queue,
                cancel_event_holder[0],
            ),
            daemon=True,
        )
        t.start()

    def on_stop() -> None:
        if not running_var.get():
            return
        ev = cancel_event_holder[0]
        if ev is not None and not ev.is_set():
            ev.set()
            stop_btn.config(state="disabled")
            log_queue.put(("log", "⏹ 正在停止..."))

    run_btn = ttk.Button(root, text="开始处理", command=on_run)
    run_btn.grid(row=10, column=0, pady=8, sticky="ew", padx=(8, 4))

    # v1.8.1+ 停止按钮：初始 disabled；on_run 时启用；on_stop / 完成时禁用
    stop_btn = ttk.Button(root, text="停止", command=on_stop, state="disabled")
    stop_btn.grid(row=10, column=1, pady=8, sticky="ew", padx=4)

    # v1.8+ dry-run：执行后启用"打开预览目录"按钮
    def _open_preview_dir() -> None:
        target = preview_dir_var.get()
        if not target:
            messagebox.showinfo("提示", "未指定预览目录；查看 tmpdir 默认值请用 CLI")
            return
        p = Path(target)
        if not p.exists():
            messagebox.showwarning("提示", f"目录不存在：{p}")
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            elif sys.platform.startswith("win"):
                os.startfile(str(p))  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("打开失败", str(e))

    open_preview_btn = ttk.Button(
        root, text="打开预览目录", command=_open_preview_dir, state="disabled"
    )
    open_preview_btn.grid(row=10, column=2, pady=8, sticky="ew", padx=(4, 8))

    # 日志（v2.2.1+：行号 +1）
    ttk.Label(root, text="日志:").grid(row=11, column=0, sticky="nw", padx=8, pady=(8, 0))
    log_frame = ttk.Frame(root)
    log_frame.grid(row=12, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 8))
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    root.rowconfigure(12, weight=1)

    log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
    log_text.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(log_frame, orient="vertical", command=log_text.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    log_text.configure(yscrollcommand=scroll.set)
    log_text.tag_configure("error", foreground="red")

    def poll_queue() -> None:
        try:
            while True:
                tag, msg = log_queue.get_nowait()
                log_text.configure(state="normal")
                log_text.insert(tk.END, msg + "\n", tag if tag == "error" else ())
                log_text.see(tk.END)
                log_text.configure(state="disabled")
                if tag in ("done", "error"):
                    progress.stop()
                    run_btn.config(state="normal")
                    stop_btn.config(state="disabled")
                    running_var.set(False)
                    # v1.8+ dry-run 完成后启用"打开预览目录"按钮
                    if tag == "done" and dry_run_var.get() and preview_dir_var.get():
                        open_preview_btn.config(state="normal")
                    if tag == "error":
                        messagebox.showerror("处理出错", msg)
        except queue.Empty:
            pass
        root.after(80, poll_queue)

    poll_queue()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
