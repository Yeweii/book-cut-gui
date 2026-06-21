"""GUI 模块 smoke test：仅在有 Tk 显示环境时跑。"""

from __future__ import annotations

import os
import sys

import pytest


@pytest.mark.skipif(sys.platform == "win32" and not os.environ.get("DISPLAY"), reason="无显示")
def test_gui_module_loads():
    """GUI 模块可正常导入。"""
    from book_cut import gui

    assert hasattr(gui, "run_gui")
    assert callable(gui.run_gui)


def test_queue_writer_captures_messages():
    """_QueueWriter 把写入的消息推入队列。"""
    import queue

    from book_cut.gui import _QueueWriter

    q: queue.Queue = queue.Queue()
    w = _QueueWriter(q, "log")
    w.write("hello\n")
    w.write("\n")  # 空白消息应被忽略
    w.flush()
    tag, msg = q.get_nowait()
    assert tag == "log"
    assert msg == "hello"
    assert q.empty()
