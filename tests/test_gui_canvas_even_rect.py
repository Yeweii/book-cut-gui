"""v2.3+ CropCanvas set_profile / get_profile 奇偶页 roundtrip 测试。

对应 bug：v2.3 把 ManualCropProfile 拆成 odd_page + even_page 时，set_profile
只用了奇页公式（L=inner, R=W-outer），没考虑偶页 inner/outer 互换语义，
导致偶页拖框窗口打开时矩形已经显示在镜像位置，用户视觉补偿拖动后，
get_profile 仍返回镜像 padding → 偶页始终按镜像裁剪。

本测试验证：
- T1: 偶页 set_profile 算出的 rect 不应等于镜像公式
- T2: set_profile → get_profile 对奇页/偶页都应 identity roundtrip
- T3: 用户实际拖框后的 padding 不再被强制镜像
"""

from __future__ import annotations

import pytest


def _make_canvas(is_even: bool):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("无 Tk 显示环境")

    from PIL import Image

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile
    from book_cut.gui_canvas import CropCanvas

    img = Image.new("L", (1000, 1000), 255)
    canvas = CropCanvas(
        root,
        img,
        profile=ManualCropProfile(
            odd_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
            even_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
        ),
        is_even=is_even,
    )
    return root, canvas


# ----------------------------------------------------------------------------
# T1: 偶页 set_profile 用 L=outer, R=W-inner（不能是 L=inner, R=W-outer）
# ----------------------------------------------------------------------------


def test_set_profile_even_uses_swapped_formula():
    """偶页 inner=W-R（右 padding）、outer=L（左 padding）→ 矩形 L=outer, R=W-inner。"""
    root, canvas = _make_canvas(is_even=True)

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile

    # inner=30（右边留 30px）→ R_rect = W - 30 = 970
    # outer=80（左边留 80px）→ L_rect = 80
    p_even = PageCropProfile(top=50, bottom=40, inner=30, outer=80)
    canvas.set_profile(ManualCropProfile(
        odd_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
        even_page=p_even,
    ))
    rect = canvas._rect
    assert rect == (80, 50, 970, 960), (
        f"偶页 set_profile 应得 (80, 50, 970, 960)，实得 {rect}（注意：镜像公式会得 (30, 50, 920, 960)）"
    )
    root.destroy()


# ----------------------------------------------------------------------------
# T2: 奇页 set_profile 不应受影响
# ----------------------------------------------------------------------------


def test_set_profile_odd_unchanged():
    """奇页 inner=L（左 padding）、outer=W-R（右 padding）→ 矩形 L=inner, R=W-outer。"""
    root, canvas = _make_canvas(is_even=False)

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile

    # 奇页：inner=80（左 80px）→ L=80；outer=30（右 30px）→ R=W-30=970
    p_odd = PageCropProfile(top=50, bottom=40, inner=80, outer=30)
    canvas.set_profile(ManualCropProfile(
        odd_page=p_odd,
        even_page=PageCropProfile(top=0, bottom=0, inner=0, outer=0),
    ))
    rect = canvas._rect
    assert rect == (80, 50, 970, 960), f"奇页 set_profile 应得 (80, 50, 970, 960)，实得 {rect}"
    root.destroy()


# ----------------------------------------------------------------------------
# T3: set_profile → get_profile 对奇偶页都应 identity
# ----------------------------------------------------------------------------


def test_roundtrip_even():
    """偶页：set_profile 后立即 get_profile 必须等于原 profile（不能产生镜像）。"""
    root, canvas = _make_canvas(is_even=True)

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile

    p_even = PageCropProfile(top=50, bottom=40, inner=30, outer=80)
    prof = ManualCropProfile(
        odd_page=PageCropProfile(top=11, bottom=22, inner=33, outer=44),
        even_page=p_even,
    )
    canvas.set_profile(prof)
    got = canvas.get_profile()
    assert got.even_page == p_even, (
        f"偶页 roundtrip 失败: expected {p_even}, got {got.even_page} "
        f"（注意：修复前会得 inner=80, outer=30 — 镜像版本）"
    )
    root.destroy()


def test_roundtrip_odd():
    """奇页：set_profile 后立即 get_profile 必须等于原 profile。"""
    root, canvas = _make_canvas(is_even=False)

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile

    p_odd = PageCropProfile(top=50, bottom=40, inner=80, outer=30)
    prof = ManualCropProfile(
        odd_page=p_odd,
        even_page=PageCropProfile(top=55, bottom=66, inner=77, outer=88),
    )
    canvas.set_profile(prof)
    got = canvas.get_profile()
    assert got.odd_page == p_odd, (
        f"奇页 roundtrip 失败: expected {p_odd}, got {got.odd_page}"
    )
    root.destroy()


# ----------------------------------------------------------------------------
# T4: 用户拖框后 padding 不再被强制镜像（关键用户场景）
# ----------------------------------------------------------------------------


def test_user_drag_even_preserves_dragged_padding():
    """模拟用户场景：偶页 IntVar=默认 (50,40,30,80) → 打开拖框 → 不动 → 应用。

    v2.3+ 修复后：不动直接应用，get_profile 返回的 even_page 应等于 IntVar 原值
    （而不是镜像版本 (50,40,80,30)）。
    """
    root, canvas = _make_canvas(is_even=True)

    from book_cut.detect.manual import ManualCropProfile, PageCropProfile

    p_even = PageCropProfile(top=50, bottom=40, inner=30, outer=80)
    canvas.set_profile(ManualCropProfile(
        odd_page=PageCropProfile(top=50, bottom=40, inner=30, outer=80),
        even_page=p_even,
    ))
    # 用户什么都没拖，直接应用
    got = canvas.get_profile()
    assert got.even_page == p_even, (
        f"用户不拖直接应用时，偶页 padding 应保持 (T=50,B=40,I=30,O=80)，"
        f"实得 {got.even_page}（修复前会被强制成 (50,40,80,30)）"
    )
    root.destroy()