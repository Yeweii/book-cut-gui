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
from book_cut.pipeline import run_pipeline

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
        log_queue.put(("error", f"❌ {e}"))
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
            "binarize": binarize_var.get(),
            "format": format_var.get(),
            "pdf": pdf_var.get(),
            "deskew": deskew_var.get(),
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
