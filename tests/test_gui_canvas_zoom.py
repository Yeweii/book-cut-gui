"""v2.2.3+ CropCanvas 缩放 + 滚动条测试。

对应 issue：拖框 Toplevel 不支持缩放，大图（5000×7000 → canvas 857×1200）超出
1000×820 Toplevel 视口，底部被切，看不到也拖不到。

测试覆盖：
- T1: CropCanvas.set_scale(new_scale) 改 _scale + config(width/height)
- T2: fit_to_size(max_w, max_h) 计算正确 scale（缩到能放下，且不超 1.0）
- T3: zoom_in / zoom_out 按 1.25× 缩放
- T4: GUI Toplevel 含 Scrollbar 绑定（xscrollcommand / yscrollcommand）
- T5: Toplevel 工具栏含 "适应窗口" / "放大" / "缩小" 按钮
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

GUI_PATH = Path(__file__).resolve().parent.parent / "src" / "book_cut" / "gui.py"
CANVAS_PATH = Path(__file__).resolve().parent.parent / "src" / "book_cut" / "gui_canvas.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# T1: CropCanvas.set_scale 改 _scale + config(width/height)
# ----------------------------------------------------------------------------


def test_cropcanvas_set_scale_changes_dimensions():
    """set_scale(new_scale) 改 self._scale 且 config(width/height) 重设画布尺寸。"""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("无 tkinter")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    img = Image.new("L", (1000, 800), 255)
    profile = ManualCropProfile(top=10, bottom=10, inner=10, outer=10)
    canvas = CropCanvas(root, img, profile=profile, max_display=2000)
    canvas.set_scale(0.5)
    # 0.5 × 1000 = 500, 0.5 × 800 = 400
    assert canvas._scale == 0.5
    assert canvas._disp_w == 500
    assert canvas._disp_h == 400
    # Canvas 配置 width 应匹配（winfo_reqwidth 含 highlight border 不直接测）
    assert int(canvas.cget("width")) == 500
    assert int(canvas.cget("height")) == 400

    root.destroy()


# ----------------------------------------------------------------------------
# T2: fit_to_size 算 best scale
# ----------------------------------------------------------------------------


def test_cropcanvas_fit_to_size_computes_best_scale():
    """fit_to_size(max_w=400, max_h=300) 对 1000×800 图应选 0.3（受 height 限制）。"""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("无 tkinter")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    img = Image.new("L", (1000, 800), 255)
    profile = ManualCropProfile(top=10, bottom=10, inner=10, outer=10)
    canvas = CropCanvas(root, img, profile=profile, max_display=2000)

    # max_w=400 → scale_w=0.4；max_h=300 → scale_h=0.375；min=0.375
    canvas.fit_to_size(max_w=400, max_h=300)
    assert canvas._scale == pytest.approx(0.375, abs=1e-6)
    assert canvas._disp_w == 375
    assert canvas._disp_h == 300

    root.destroy()


def test_cropcanvas_fit_to_size_caps_at_1():
    """fit_to_size 不放大（max > 原图时仍保持 1.0）。"""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("无 tkinter")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    img = Image.new("L", (100, 100), 255)
    canvas = CropCanvas(
        root, img, profile=ManualCropProfile(top=1, bottom=1, inner=1, outer=1), max_display=2000
    )
    canvas.fit_to_size(max_w=2000, max_h=2000)
    # 100×100 不会放大，scale 仍是 1.0
    assert canvas._scale == 1.0

    root.destroy()


def test_cropcanvas_fit_to_size_invalid_raises():
    """fit_to_size(max_w=0) 应抛 ValueError。"""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("无 tkinter")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    canvas = CropCanvas(
        root, Image.new("L", (10, 10), 255), profile=ManualCropProfile(top=0, bottom=0, inner=0, outer=0)
    )
    with pytest.raises(ValueError, match="max_w"):
        canvas.fit_to_size(max_w=0, max_h=10)

    root.destroy()


# ----------------------------------------------------------------------------
# T3: zoom_in / zoom_out 按 1.25× 缩放
# ----------------------------------------------------------------------------


def test_cropcanvas_zoom_in_out():
    """zoom_in / zoom_out 按 1.25 系数缩放。"""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("无 tkinter")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    canvas = CropCanvas(
        root,
        Image.new("L", (1000, 1000), 255),
        profile=ManualCropProfile(top=0, bottom=0, inner=0, outer=0),
    )
    initial = canvas._scale
    canvas.zoom_in(factor=1.25)
    assert canvas._scale == pytest.approx(initial * 1.25, abs=1e-6)
    canvas.zoom_out(factor=1.25)
    assert canvas._scale == pytest.approx(initial, abs=1e-6)

    root.destroy()


# ----------------------------------------------------------------------------
# T4: GUI Toplevel 含 Scrollbar 绑定
# ----------------------------------------------------------------------------


def test_sample_window_has_scrollbars():
    """_show_sample_crop_window 内的 CropCanvas 应绑定 xscrollcommand/yscrollcommand。"""
    src = _read(GUI_PATH)
    # 找 _show_sample_crop_window 到下一个 ttk.Button(manual_btn_frame) 为止
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    assert m is not None, "找不到 _show_sample_crop_window 边界"
    body = m.group(0)
    assert "Scrollbar" in body, "样本页 Toplevel 缺少 Scrollbar"
    assert "xscrollcommand" in body, "Canvas 未绑定 xscrollcommand"
    assert "yscrollcommand" in body, "Canvas 未绑定 yscrollcommand"


# ----------------------------------------------------------------------------
# T5: Toplevel 工具栏含缩放按钮
# ----------------------------------------------------------------------------


def test_sample_window_has_zoom_buttons():
    """_show_sample_crop_window 工具栏应含"适应窗口" / "放大" / "缩小"按钮。"""
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)
    for label in ("适应窗口", "放大", "缩小"):
        assert label in body, f"工具栏缺少按钮：{label}"


# ----------------------------------------------------------------------------
# T6: v2.2.4+ 移除冗余 100% 按钮（避免和百分比 label 重复）
# ----------------------------------------------------------------------------


def test_no_redundant_100_percent_button():
    """不应有 text="100%" 的按钮（与百分比 label 重复，看起来像空白按钮）。

    v2.2.3 引入了 100% 按钮和 zoom_pct_var label 都显示"100%"，用户反馈
    100% 按钮看起来是空白按钮。本测试确保不再有这种重复。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)
    assert 'text="100%"' not in body, (
        "存在 text='100%' 按钮——会和百分比 label 重复（v2.2.3 UX bug）"
    )


# ----------------------------------------------------------------------------
# T7: v2.2.4+ 底部 "应用" 按钮必须存在
# ----------------------------------------------------------------------------


def test_apply_button_in_sample_window():
    """_show_sample_crop_window 必须有"应用"按钮（v2.2.4+ 必填项）。

    v2.2.3 反馈：用户没看到底部"应用"按钮，怀疑被工具栏挤掉或裁切。
    本测试静态分析源码中必须存在 "应用" 按钮。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)
    # "应用" 按钮：在 btn_frame 里，command 调 _on_apply
    assert 'text="应用"' in body, "底部缺少'应用'按钮"
    assert "_on_apply" in body, "应用按钮缺少 _on_apply 回调"


# ----------------------------------------------------------------------------
# T8: v2.2.5+ 输入路径浏览 — 统一"文件 / 文件夹"对话框
# ----------------------------------------------------------------------------


def test_browse_input_uses_unified_dialog():
    """v2.2.5+ browse_input 必须用统一 Toplevel（不要 askdirectory→askopenfilename 2 步）。

    原行为：先弹 askdirectory（选择文件夹），取消后才弹 askopenfilename（选文件）。
    用户体验割裂。新行为：单 Toplevel 同时支持两种选择。
    """
    src = _read(GUI_PATH)
    # 找 browse_input 函数体（用下一个 def/class 边界）
    m = re.search(
        r"def browse_input.*?(?=\n    def |\nclass |\Z)", src, flags=re.DOTALL
    )
    assert m is not None, "找不到 browse_input 函数"
    body = m.group(0)
    # 新版必须用 Toplevel
    assert "Toplevel" in body, (
        "browse_input 没用 Toplevel（v2.2.5 之前的 2 步 askdialog 已被替代）"
    )
    # 必须有"选择文件"和"选择文件夹"两个按钮
    assert "选择文件" in body, "browse_input 缺少'选择文件'按钮"
    assert "选择文件夹" in body, "browse_input 缺少'选择文件夹'按钮"
