"""book-cut GUI 启动器：仅给 PyInstaller .app 打包用。

直接调 run_gui()，绕过 CLI 的 argparse（不要求 --input/--output）。
这样 .app 双击 = 启动 GUI 窗口，不弹 terminal、不要求参数。
"""

from __future__ import annotations

import sys


def main() -> int:
    # 兼容 PyInstaller 打包：GUI 模式下 sys.stdout 可能为 None
    # 不需要 print，纯窗口交互
    try:
        from book_cut.gui import run_gui

        run_gui()
    except Exception as e:  # noqa: BLE001
        # GUI 启动失败时尽量把错误暴露出来（macOS 会以崩溃报告形式）
        import traceback

        sys.stderr.write(f"book-cut GUI 启动失败:\n{traceback.format_exc()}\n")
        sys.stderr.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
