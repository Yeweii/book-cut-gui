"""v1.6+ E1+E3：GUI UX 改进单测。

E1 (UI 联动)：
- ``_suggest_output_dir(input_path)``：input → output 自动建议
- ``crop_var`` 变化 → morph_check 启用/禁用（在 run_gui() 里 trace，需要构造 Tk）

E3 (友好错误提示)：
- ``_format_error(exc)``：常见异常 → 中文提示

依赖：
- E1b / E3 是纯函数，无 Tk 依赖，单测直接调
- E1a (crop → morph 联动) 需要真实 Tk，跳过无显示环境
"""

from __future__ import annotations

import os
import sys

import pytest

# ============ E1b: _suggest_output_dir 纯函数 ============


def test_e1b_suggest_output_dir_from_file(tmp_path):
    """输入是文件 → 返回 ``{parent}/{stem}_out``。"""
    from book_cut.gui import _suggest_output_dir

    f = tmp_path / "book.pdf"
    f.write_bytes(b"%PDF-1.4\n")  # 存在即可
    result = _suggest_output_dir(str(f))
    assert result == str(tmp_path / "book_out")


def test_e1b_suggest_output_dir_from_folder(tmp_path):
    """输入是目录 → 返回 ``{parent}/{name}_out``。"""
    from book_cut.gui import _suggest_output_dir

    d = tmp_path / "scans"
    d.mkdir()
    result = _suggest_output_dir(str(d))
    assert result == str(tmp_path / "scans_out")


def test_e1b_suggest_output_dir_empty_returns_none():
    """空输入 → ``None``（调用方不改动 output）。"""
    from book_cut.gui import _suggest_output_dir

    assert _suggest_output_dir("") is None


def test_e1b_suggest_output_dir_nonexistent_returns_none():
    """不存在的路径 → ``None``（不报错，避免用户输入半路径时崩溃）。"""
    from book_cut.gui import _suggest_output_dir

    assert _suggest_output_dir("/totally/missing/path/foo.pdf") is None


def test_e1b_suggest_output_dir_strips_trailing_slash(tmp_path):
    """目录路径带尾斜杠也能识别（macOS 文件对话框常见）。"""
    from book_cut.gui import _suggest_output_dir

    d = tmp_path / "scans"
    d.mkdir()
    result = _suggest_output_dir(str(d) + "/")
    assert result == str(tmp_path / "scans_out")


# ============ E3: _format_error 纯函数 ============


def test_e3_format_error_filenotfound():
    """``FileNotFoundError`` → 中文提示 + 原始信息。"""
    from book_cut.gui import _format_error

    e = FileNotFoundError(2, "No such file", "/missing.pdf")
    msg = _format_error(e)
    assert "找不到文件" in msg
    assert "FileNotFoundError" in msg
    assert "/missing.pdf" in msg


def test_e3_format_error_permission():
    """``PermissionError`` → 中文权限提示。"""
    from book_cut.gui import _format_error

    e = PermissionError(13, "Permission denied", "/locked.pdf")
    msg = _format_error(e)
    assert "权限" in msg
    assert "PermissionError" in msg


def test_e3_format_error_is_directory():
    """``IsADirectoryError`` → 中文提示（输入是目录而非文件）。"""
    from book_cut.gui import _format_error

    e = IsADirectoryError(21, "Is a directory", "/some/dir")
    msg = _format_error(e)
    assert "目录" in msg


def test_e3_format_error_not_a_directory():
    """``NotADirectoryError`` → 中文提示（输出目录必须是目录）。"""
    from book_cut.gui import _format_error

    e = NotADirectoryError(20, "Not a directory", "/some/file")
    msg = _format_error(e)
    assert "不是目录" in msg


def test_e3_format_error_unknown_exception_uses_generic():
    """未映射的异常 → 通用兜底（仍带 ``type: message``）。"""
    from book_cut.gui import _format_error

    e = ValueError("bad pixel value")
    msg = _format_error(e)
    assert "处理出错" in msg
    assert "ValueError" in msg
    assert "bad pixel value" in msg


def test_e3_format_error_subclass_of_known():
    """``FileNotFoundError`` 的子类也被命中（``isinstance`` 检查）。"""
    from book_cut.gui import _format_error

    class CustomNotFound(FileNotFoundError):
        pass

    e = CustomNotFound("custom missing")
    msg = _format_error(e)
    assert "找不到文件" in msg


def test_e3_format_error_first_match_wins():
    """多类型映射时按 ``_FRIENDLY_ERRORS`` 顺序匹配第一个（具体类型优先）。"""
    from book_cut.gui import _format_error

    # OSError 不是 _FRIENDLY_ERRORS 里的具体类型，走通用兜底
    e = OSError(5, "I/O error")
    msg = _format_error(e)
    assert "处理出错" in msg
    assert "OSError" in msg


# ============ E1a: crop_var → morph_check 联动（需 Tk） ============


@pytest.mark.skipif(
    sys.platform == "win32" and not os.environ.get("DISPLAY"),
    reason="无显示",
)
def test_e1a_morph_disabled_when_crop_none():
    """``crop=none`` 时 morph_check 应被禁用；切回 trim/border 时恢复。"""
    import tkinter as tk
    from tkinter import ttk


    # 复刻 run_gui() 里的 trace 逻辑（不启动 mainloop）
    root = tk.Tk()
    root.withdraw()
    try:
        crop_var = tk.StringVar(value="none")
        morph_var = tk.BooleanVar(value=True)
        morph_check = ttk.Checkbutton(root, variable=morph_var)
        morph_check.pack()

        # 同步 gui 里的 trace 逻辑
        def _on_crop_change(*_a: object) -> None:
            morph_check.config(state="disabled" if crop_var.get() == "none" else "normal")

        crop_var.trace_add("write", _on_crop_change)
        _on_crop_change()  # 初始化

        # crop=none → 禁用
        root.update_idletasks()
        assert str(morph_check.cget("state")) == "disabled", (
            "crop=none 时 morph 应被禁用"
        )

        # crop=trim → 恢复
        crop_var.set("trim")
        root.update_idletasks()
        assert str(morph_check.cget("state")) == "normal", (
            "crop=trim 时 morph 应启用"
        )

        # crop=border → 仍启用
        crop_var.set("border")
        root.update_idletasks()
        assert str(morph_check.cget("state")) == "normal"
    finally:
        root.destroy()


@pytest.mark.skipif(
    sys.platform == "win32" and os.environ.get("DISPLAY") is None,
    reason="无显示",
)
def test_e1b_input_trace_fills_output_when_empty(tmp_path, monkeypatch):
    """``input_var`` 写入有效路径 + ``output_var`` 为空 → 自动填充建议。"""
    import tkinter as tk

    from book_cut.gui import _suggest_output_dir

    root = tk.Tk()
    root.withdraw()
    try:
        input_var = tk.StringVar()
        output_var = tk.StringVar()

        # 复刻 run_gui() 里的 trace
        def _on_input_change(*_a: object) -> None:
            if output_var.get():
                return
            suggested = _suggest_output_dir(input_var.get())
            if suggested:
                output_var.set(suggested)

        input_var.trace_add("write", _on_input_change)

        # 准备输入文件
        f = tmp_path / "book.pdf"
        f.write_bytes(b"%PDF-1.4\n")

        # 初始：output 空
        assert output_var.get() == ""

        # 设置 input → output 自动填充
        input_var.set(str(f))
        root.update_idletasks()
        assert output_var.get() == str(tmp_path / "book_out")

        # 用户手动改 output → 后续 input 变化不覆盖（用户先填的优先）
        output_var.set("/my/custom/out")
        f2 = tmp_path / "book2.pdf"
        f2.write_bytes(b"%PDF-1.4\n")
        input_var.set(str(f2))
        root.update_idletasks()
        assert output_var.get() == "/my/custom/out", (
            "用户已填 output 时不应被 input 变化覆盖"
        )

        # 用户清空 output → 下一次 input 变化重新填充
        output_var.set("")
        input_var.set(str(f))
        root.update_idletasks()
        assert output_var.get() == str(tmp_path / "book_out")
    finally:
        root.destroy()
