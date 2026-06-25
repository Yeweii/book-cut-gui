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
    from book_cut.detect.manual import PageCropProfile

    profile = ManualCropProfile(
        odd_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
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

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    img = Image.new("L", (1000, 800), 255)
    profile = ManualCropProfile(
        odd_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
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

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    img = Image.new("L", (100, 100), 255)
    canvas = CropCanvas(
        root, img, profile=ManualCropProfile(
            odd_page=PageCropProfile(top=1, bottom=1, inner=1, outer=1),
            even_page=PageCropProfile(top=1, bottom=1, inner=1, outer=1),
        ), max_display=2000
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

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    canvas = CropCanvas(
        root, Image.new("L", (10, 10), 255), profile=ManualCropProfile(
            odd_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
            even_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
        )
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

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile
    from book_cut.gui_canvas import CropCanvas

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    canvas = CropCanvas(
        root,
        Image.new("L", (1000, 1000), 255),
        profile=ManualCropProfile(
            odd_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
            even_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
        ),
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
    本测试静态分析源码中必须存在 "应用" 按钮（v2.2.7+ 接受带前缀如 "✓ 应用"）。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)
    # "应用" 按钮：text 含"应用"（v2.2.7+ 可能是 "✓ 应用" / "应用" 等）
    assert re.search(r'text\s*=\s*"[^"]*应用', body), "缺少'应用'按钮"
    assert "_on_apply" in body, "应用按钮缺少 _on_apply 回调"


# ----------------------------------------------------------------------------
# T7b: v2.2.7+ "应用" 按钮必须在 apply_row（独立行，恒可见）
# ----------------------------------------------------------------------------


def test_apply_button_in_apply_row_v227():
    """v2.2.7+ '应用' 按钮必须在 apply_row（toolbar 下方独立行），永远可见。

    v2.2.4 放底部 btn_frame → 被 canvas 挤出可见区（用户截图）
    v2.2.6 放 toolbar 右侧 → 被中文 radio 挤成 1x1 不可见（实测 winfo_width=1）
    v2.2.7 单独一行 apply_row，紧贴 toolbar 下方，固定高，恒可见
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)

    # 1) apply_row 里必须有"应用"按钮（ttk.Button(apply_row, text=..."应用"...)）
    has_apply_in_row = re.search(
        r'ttk\.Button\(\s*apply_row[^)]*text\s*=\s*"[^"]*应用', body, flags=re.DOTALL
    )
    assert has_apply_in_row, (
        "v2.2.7+ 修复：'应用'按钮必须在 apply_row（独立行，恒可见）"
    )

    # 2) "应用"按钮必须 pack(side="right") 靠右显示
    apply_btn_block = re.search(
        r'ttk\.Button\(\s*apply_row.*?应用.*?\)\s*\.pack\(([^)]+)\)',
        body,
        flags=re.DOTALL,
    )
    assert apply_btn_block is not None, "apply_row'应用'按钮缺少 .pack() 调用"
    pack_args = apply_btn_block.group(1)
    assert 'side="right"' in pack_args, (
        f"'应用'按钮应 pack(side='right') 靠右；当前: {pack_args!r}"
    )

    # 3) 不能再把'应用'塞进 toolbar（v2.2.6 教训：被挤成 1x1）
    has_apply_in_toolbar = re.search(
        r'ttk\.Button\(\s*toolbar[^)]*text\s*=\s*"[^"]*应用', body, flags=re.DOTALL
    )
    assert not has_apply_in_toolbar, (
        "v2.2.7+：'应用'按钮禁止放 toolbar（v2.2.6 教训：被中文 radio 挤成 1x1）"
    )


# ----------------------------------------------------------------------------
# T7c: v2.2.7+ apply_row 独立行（不被 toolbar 挤压）
# ----------------------------------------------------------------------------


def test_apply_row_is_independent_of_toolbar():
    """v2.2.7+ apply_row 必须是独立 Frame（不再被 toolbar 挤压）。

    v2.2.6 教训：把"应用"塞进 toolbar 右侧，pack 后 winfo_width=1
    （中文 radio 占满 984px 空间，右侧按钮被挤成 1x1 不可见）。

    v2.2.7 修复：apply_row 独立 Frame，紧贴 toolbar 下方，固定高
    （Separator + 按钮行约 50px），不受 toolbar 控件数量影响。

    v2.2.7.1 调整：apply_bar 改 pack(side="bottom")，让按钮在 Toplevel
    底部（自然位置）恒可见，与 canvas 互相独立。

    本测试用 pack_info 验证 apply_row 不在 toolbar 内。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)

    # 1) apply_row 必须用独立 Frame（"apply_row = ttk.Frame(apply_bar)"）
    has_apply_row = re.search(
        r"apply_row\s*=\s*ttk\.Frame\(", body
    )
    assert has_apply_row, (
        "v2.2.7+：apply_row 必须是独立 Frame（避免被 toolbar 挤压）"
    )

    # 2) apply_row 必须 pack(side="top", fill="x") 而不是 expand
    row_pack = re.search(
        r"apply_row\.pack\(\s*([^)]+)\s*\)", body
    )
    assert row_pack is not None, "apply_row 缺少 .pack() 调用"
    pack_args = row_pack.group(1)
    assert 'side="top"' in pack_args, (
        f"apply_row 应 pack(side='top') 在 toolbar 下方；当前: {pack_args!r}"
    )
    assert "expand=" not in pack_args or "expand=0" in pack_args or "expand=False" in pack_args, (
        f"apply_row 不应 expand（保证固定高，不被 canvas 抢空间）；当前: {pack_args!r}"
    )


# ----------------------------------------------------------------------------
# T7d: v2.2.7.1+ apply_bar 必须在 Toplevel 底部（side="bottom"），常驻可见
# ----------------------------------------------------------------------------


def test_apply_bar_packed_at_bottom_v2271():
    """v2.2.7.1+ apply_bar 必须 pack(side="bottom")，让按钮在 Toplevel 底部恒可见。

    v2.2.7 把 apply_bar 放在 toolbar 下方（side="top"），结果按钮在
    toolbar 和 canvas 中间，位置不自然；用户反馈"需要图片缩小到一定程度
    才可以显示底部三个按钮"——视觉上像在 canvas 内部被遮。

    修复：apply_bar 改 pack(side="bottom", fill="x")，固定在 Toplevel
    最底部，不与 canvas 互相影响，任何缩放下都可见。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)

    # 抓 apply_bar 的 pack 调用
    bar_pack = re.search(
        r"apply_bar\.pack\(\s*([^)]+)\s*\)", body
    )
    assert bar_pack is not None, "apply_bar 缺少 .pack() 调用"
    pack_args = bar_pack.group(1)
    assert 'side="bottom"' in pack_args, (
        f"v2.2.7.1+：apply_bar 必须 pack(side='bottom') 在 Toplevel 底部；当前: {pack_args!r}"
    )
    assert 'fill="x"' in pack_args, (
        f"apply_bar 必须 fill='x'（横满）；当前: {pack_args!r}"
    )


# ----------------------------------------------------------------------------
# T7e: v2.2.7.2+ apply_bar 必须在 canvas 之前 pack（避免被 expand 抢空间）
# ----------------------------------------------------------------------------


def test_apply_bar_packed_before_canvas_v2272():
    """v2.2.7.2+ apply_bar.pack() 必须在 canvas_frame.pack() 之前。

    关键修复：v2.2.7.1 只改 side="bottom" 还不够——pack 顺序决定
    expand 行为。如果 canvas_frame 先 pack(expand=True)，它会抢
    走所有剩余空间，apply_bar 后 pack 时已被挤掉。

    Tk pack 语义：top expand 抢占剩余空间，bottom 项要"先到先得"。
    修复：apply_bar 先 pack(side="bottom") 占住底部，canvas 后
    pack(side="top", expand=True) 只能拿到中间剩余空间。
    """
    src = _read(GUI_PATH)
    m = re.search(
        r"def _show_sample_crop_window.*?ttk\.Button\(manual_btn_frame",
        src,
        flags=re.DOTALL,
    )
    body = m.group(0)

    # 在源码里找两个 pack() 调用的字符偏移
    # 注意：找**不在注释里**的 pack()——comments 含"apply_bar.pack" / "canvas_frame.pack" 字符串
    apply_bar_pack_pos = body.find("apply_bar.pack(")
    canvas_frame_pack_pos = body.find("canvas_frame.pack(")

    # 如果第一个 canvas_frame.pack( 出现在 # 注释里，跳到下一个
    if canvas_frame_pack_pos > 0:
        # 找 # 注释行
        line_start = body.rfind("\n", 0, canvas_frame_pack_pos) + 1
        if body[line_start:canvas_frame_pack_pos].strip().startswith("#"):
            # 跳过注释行
            canvas_frame_pack_pos = body.find(
                "canvas_frame.pack(", canvas_frame_pack_pos + 1
            )

    assert apply_bar_pack_pos > 0, "apply_bar.pack 没找到"
    assert canvas_frame_pack_pos > 0, "canvas_frame.pack 没找到"

    assert apply_bar_pack_pos < canvas_frame_pack_pos, (
        f"v2.2.7.2+：apply_bar.pack() (offset={apply_bar_pack_pos}) "
        f"必须在 canvas_frame.pack() (offset={canvas_frame_pack_pos}) 之前；"
        f"否则 canvas expand=True 抢所有空间，apply_bar 被挤掉"
    )


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
