"""Tkinter GUI 主窗口。"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from book_cut import __version__
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
) -> None:
    """在线程中跑 pipeline；日志通过 queue 推到主线程。"""
    args = argparse.Namespace(input=str(input_path), output=str(output_path), **values)

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = _QueueWriter(log_queue, "log")
    sys.stderr = _QueueWriter(log_queue, "log")
    try:
        run_pipeline(args)
        log_queue.put(("done", "✅ 处理完成"))
    except Exception as e:  # noqa: BLE001
        log_queue.put(("error", _format_error(e)))
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------


def run_gui() -> None:
    root = tk.Tk()
    root.title(f"古籍双页切分工具 v{__version__}")
    root.geometry("720x680")
    root.minsize(600, 560)

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

    log_queue: queue.Queue = queue.Queue()

    # ---- 样式 ----
    style = ttk.Style()
    try:
        style.theme_use("aqua" if sys.platform == "darwin" else "clam")
    except tk.TclError:
        pass

    # ---- 布局 ----
    pad = {"padx": 8, "pady": 4}
    root.columnconfigure(1, weight=1)

    # 标题
    ttk.Label(root, text="古籍双页切分工具", font=("Helvetica", 14, "bold")).grid(
        row=0, column=0, columnspan=3, pady=(12, 8)
    )

    # 输入
    ttk.Label(root, text="输入路径:").grid(row=1, column=0, sticky="e", **pad)
    ttk.Entry(root, textvariable=input_var).grid(row=1, column=1, sticky="ew", **pad)

    def browse_input() -> None:
        path = filedialog.askdirectory(title="选择文件夹")
        if not path:
            path = filedialog.askopenfilename(
                title="选择 PDF 或图片",
                filetypes=[
                    ("PDF", "*.pdf"),
                    ("图片", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp"),
                    ("所有", "*.*"),
                ],
            )
        if path:
            input_var.set(path)

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
        [("gutter", "中缝（推荐）"), ("border", "版框线"), ("half", "对半")]
    ):
        ttk.Radiobutton(split_frame, text=label, variable=split_var, value=val).grid(
            row=0, column=i, padx=4
        )

    # 裁切
    ttk.Label(root, text="单页裁切:").grid(row=5, column=0, sticky="e", **pad)
    crop_frame = ttk.Frame(root)
    crop_frame.grid(row=5, column=1, sticky="w", **pad)
    for i, (val, label) in enumerate(
        [("none", "不裁"), ("trim", "切白边"), ("border", "版框内裁")]
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

    crop_var.trace_add("write", _on_crop_change)
    _on_crop_change()  # 初始化时跑一次对齐默认状态

    # 二值化
    ttk.Label(root, text="二值化:").grid(row=6, column=0, sticky="e", **pad)
    bin_frame = ttk.Frame(root)
    bin_frame.grid(row=6, column=1, sticky="w", **pad)
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

    # 输出格式 + PDF
    ttk.Label(root, text="输出格式:").grid(row=7, column=0, sticky="e", **pad)
    fmt_frame = ttk.Frame(root)
    fmt_frame.grid(row=7, column=1, sticky="w", **pad)
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

    # 进度条
    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.grid(row=8, column=0, columnspan=3, sticky="ew", padx=8, pady=(12, 4))

    # 执行按钮
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
        progress.start(80)

        values = {
            "split": split_var.get(),
            "crop": crop_var.get(),
            "crop_adaptive": "auto" if crop_adaptive_var.get() else "fixed",
            "paper_pages": paper_pages_var.get(),
            "binarize": binarize_var.get(),
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
        }
        t = threading.Thread(
            target=_run_pipeline_thread,
            args=(Path(input_var.get()), Path(output_var.get()), values, log_queue),
            daemon=True,
        )
        t.start()

    run_btn = ttk.Button(root, text="开始处理", command=on_run)
    run_btn.grid(row=9, column=0, columnspan=3, pady=8)

    # 日志
    ttk.Label(root, text="日志:").grid(row=10, column=0, sticky="nw", padx=8, pady=(8, 0))
    log_frame = ttk.Frame(root)
    log_frame.grid(row=11, column=0, columnspan=3, sticky="nsew", padx=8, pady=(0, 8))
    log_frame.columnconfigure(0, weight=1)
    log_frame.rowconfigure(0, weight=1)
    root.rowconfigure(11, weight=1)

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
                    running_var.set(False)
                    if tag == "error":
                        messagebox.showerror("处理出错", msg)
        except queue.Empty:
            pass
        root.after(80, poll_queue)

    poll_queue()
    root.mainloop()


if __name__ == "__main__":
    run_gui()
