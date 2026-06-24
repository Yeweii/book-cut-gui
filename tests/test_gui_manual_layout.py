"""v2.2+ GUI Manual Crop 面板布局/i18n/展开收起测试。

对应 issue：v0.3.0 首次启动时 Manual Crop 面板与二值化行 row=6 冲突，
4 个 padding spinbox 被二值化 dropdown 盖住。

测试覆盖：
- T1: 行索引不冲突（手动裁切行 ≠ 二值化行）
- T2: 控件 label 全部中文（无 Manual Crop / Top / Bottom / Inner / Outer / Mirror / Load preset / Save preset）
- T3: 展开/收起切换函数存在并能切换 manual_pad_frame / manual_btn_frame 可见性
"""

from __future__ import annotations

import re
from pathlib import Path

GUI_PATH = Path(__file__).resolve().parent.parent / "src" / "book_cut" / "gui.py"

import pytest  # noqa: E402


def _read_gui_source() -> str:
    """读 gui.py 源码（避免在 CI 装 Tk）。"""
    return GUI_PATH.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# T1: 行冲突检测
# ----------------------------------------------------------------------------


def test_manual_frame_row_not_conflict_with_binarize():
    """manual_frame.grid(row=...) 不能再与 bin_frame.grid(row=...) 用同一行。

    v0.3.0 bug：两者都用 row=6，binarize 把 manual 4 个 padding spinbox 盖住。
    """
    src = _read_gui_source()
    # 抓 manual_frame.grid(row=N, ...)
    m1 = re.search(r"manual_frame\.grid\([^)]*row\s*=\s*(\d+)", src)
    # 抓 bin_frame.grid(row=N, ...)
    m2 = re.search(r"bin_frame\.grid\([^)]*row\s*=\s*(\d+)", src)
    assert m1 is not None, "manual_frame.grid 没找到"
    assert m2 is not None, "bin_frame.grid 没找到"
    assert m1.group(1) != m2.group(1), (
        f"manual_frame 和 bin_frame 共享 row={m1.group(1)}（v0.3.0 bug 复现）"
    )


# ----------------------------------------------------------------------------
# T2: i18n - 所有 Manual Crop 相关 label 必须是中文
# ----------------------------------------------------------------------------


def test_manual_crop_labels_are_chinese():
    """Manual Crop 面板的 label / button 文本必须中文（不允许英文混进 UI）。"""
    src = _read_gui_source()
    # 抓 LabelFrame 标题
    m = re.search(r'manual_frame\s*=\s*ttk\.LabelFrame\([^)]*text\s*=\s*"([^"]+)"', src)
    assert m is not None, "manual_frame LabelFrame 没找到"
    title = m.group(1)
    assert "Manual Crop" not in title, f"Manual Crop 标题未翻译: {title!r}"
    # 至少包含"手动裁切"或等价中文
    assert "手动" in title or "裁切" in title, (
        f"LabelFrame 标题应含中文: {title!r}"
    )


def test_manual_padding_labels_are_chinese():
    """4 个 padding label（顶/底/中缝/外侧 或 上/下/内/外）必须是中文。

    不允许出现 ``text="Top:"`` / ``text="Bottom:"`` / ``text="Inner:"`` / ``text="Outer:"``。
    """
    src = _read_gui_source()
    forbidden = ['"Top:"', '"Bottom:"', '"Inner:"', '"Outer:"']
    for token in forbidden:
        assert token not in src, f"英文 padding label 未翻译: {token}"


def test_manual_mirror_label_is_chinese():
    """Mirror 复选框 label 必须是中文。"""
    src = _read_gui_source()
    # 抓 Mirror to even pages 字符串
    assert "Mirror to even pages" not in src, "Mirror to even pages 未翻译"
    # 应该有"镜像"或等价中文
    assert "镜像" in src, "应有中文'镜像'"


def test_manual_preset_buttons_are_chinese():
    """Load preset / Save preset 按钮必须是中文。"""
    src = _read_gui_source()
    assert "Load preset" not in src, "Load preset 按钮未翻译"
    assert "Save preset" not in src, "Save preset 按钮未翻译"
    assert "加载" in src, "应有'加载'按钮"
    assert "保存" in src, "应有'保存'按钮"


# ----------------------------------------------------------------------------
# T3: 展开/收起
# ----------------------------------------------------------------------------


def test_manual_expand_collapse_button_exists():
    """v2.2.1+：manual_frame 应有展开/收起按钮（Button 文本含'展开'或'收起'）。"""
    src = _read_gui_source()
    # 允许的按钮文本模式
    patterns = [
        r'text\s*=\s*"[^"]*展开[^"]*"',
        r'text\s*=\s*"[^"]*收起[^"]*"',
        r'text\s*=\s*"▶[^"]*"',
        r'text\s*=\s*"▼[^"]*"',
    ]
    found = any(re.search(p, src) for p in patterns)
    assert found, "manual_frame 缺少展开/收起按钮"


def test_manual_expand_collapse_toggle_hides_widgets():
    """展开/收起函数能切换 manual_pad_frame / manual_btn_frame 可见性。

    简单静态分析：源码里要有一个函数调用 grid_remove() / grid() 来切换 manual 子 frame。
    """
    src = _read_gui_source()
    # 必须有对 manual_pad_frame 或 manual_btn_frame 调 grid_remove 或 grid
    has_toggle = (
        "grid_remove" in src
        and ("manual_pad_frame" in src or "manual_btn_frame" in src)
    )
    assert has_toggle, (
        "manual 面板缺少展开/收起切换逻辑（grid_remove / grid）"
    )


# ----------------------------------------------------------------------------
# T4: v2.2.2+ 样本页拖框（图片 → 拖框 → 自动算 padding）
# ----------------------------------------------------------------------------


def test_sample_page_button_exists():
    """manual 面板应有"选择样本页…"按钮（v2.2.2+）。"""
    src = _read_gui_source()
    assert "选择样本页" in src, "manual 面板缺少'选择样本页…'按钮"


def test_gui_imports_cropcanvas():
    """gui.py 应 import CropCanvas（v2.2.2+ 拖框 UI 入口）。"""
    src = _read_gui_source()
    assert "from book_cut.gui_canvas import" in src, "gui.py 未 import CropCanvas"
    assert "CropCanvas" in src, "gui.py 未引用 CropCanvas"


def test_sample_page_supports_image_filetypes():
    """样本页文件选择器（_open_sample_page 上下文）应支持常见图片格式。

    静态分析：抓 _open_sample_page 函数体里的 filetypes=[...，断言至少 1 个图片扩展。
    """
    src = _read_gui_source()
    # 抓 _open_sample_page 函数到下一个 def / 顶层语句为止
    import re

    m = re.search(r"def _open_sample_page.*?(?=\n    def |\nclass |\Z)", src, flags=re.DOTALL)
    assert m is not None, "找不到 _open_sample_page 函数定义"
    body = m.group(0)
    has_image_ft = any(ext in body for ext in ["*.png", "*.jpg", "*.jpeg", "*.tif", "*.bmp"])
    assert has_image_ft, "样本页文件选择器应支持图片格式（png/jpg/tif/bmp 等）"


# ----------------------------------------------------------------------------
# T5: 纯函数：profile → 4 个 IntVar 字段
# ----------------------------------------------------------------------------


def test_apply_profile_to_vars():
    """apply_profile_to_vars(profile, vars) 把 profile 的 4 个 padding 写到 IntVar。

    v2.2.2+ 抽出来的纯函数：拖框 Toplevel 应用按钮调它把新 padding 同步到主窗口。
    单元测试不依赖 Tk：tk.IntVar 在 mock 模式下也能 set/get。
    """
    import tkinter as tk

    from book_cut.detect.manual import ManualCropProfile

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    from book_cut.gui import apply_profile_to_vars

    top = tk.IntVar(value=0)
    bottom = tk.IntVar(value=0)
    inner = tk.IntVar(value=0)
    outer = tk.IntVar(value=0)
    mirror = tk.BooleanVar(value=True)

    prof = ManualCropProfile(top=50, bottom=40, inner=80, outer=30, mirror_even=False)
    apply_profile_to_vars(prof, top, bottom, inner, outer, mirror)

    assert top.get() == 50
    assert bottom.get() == 40
    assert inner.get() == 80
    assert outer.get() == 30
    assert mirror.get() is False  # mirror_even 也会同步

    root.destroy()
