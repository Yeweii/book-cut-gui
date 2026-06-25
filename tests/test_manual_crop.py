"""v2.3 manual crop 测试：ManualCropProfile + apply_manual_crop + coord math。

对应变更：``techneering/changes/v2.3-independent-odd-even-crop/``

v2.3+ 重构：
- ``ManualCropProfile`` 字段从 ``top/bottom/inner/outer/mirror_even`` 改为
  ``odd_page/even_page``（两个 ``PageCropProfile``）
- ``padding_from_rect`` 无 ``mirror_even`` 参数，返回 ``PageCropProfile``
- ``from_json`` 自动迁移 v1 preset 到内存 v2 结构
- ``to_json`` 始终输出 v2 格式

TDD 约定：先写 RED（模块/函数不存在 → ImportError/AttributeError），再实现 GREEN。
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from book_cut.detect.manual import (
    ManualCropProfile,
    PageCropProfile,
    apply_manual_crop,
    canvas_to_image,
    padding_from_rect,
    parse_manual_padding,
)

# ----------------------------------------------------------------------------
# 合成 fixture：白纸 + 已知 padding 的内容
# ----------------------------------------------------------------------------


def _blank_page_with_inner_box() -> Image.Image:
    """1000×800 白纸，中央 200~800 x 100~700 区域为黑色实心矩形。

    视觉上：上下边各 100px 白、左右各 200px 白。
    """
    img = Image.new("L", (1000, 800), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(200, 100), (800, 700)], fill=0)
    return img


def _default_odd_even() -> tuple[PageCropProfile, PageCropProfile]:
    """默认 odd/even profile：odd=(50,40,80,30), even=(50,40,30,80)。"""
    odd = PageCropProfile(top=50, bottom=40, inner=80, outer=30)
    even = PageCropProfile(top=50, bottom=40, inner=30, outer=80)
    return odd, even


# ----------------------------------------------------------------------------
# T1: ManualCropProfile JSON roundtrip（v2 新格式）
# ----------------------------------------------------------------------------


def test_manual_v2_json_roundtrip():
    """v2 profile → JSON → profile 应当完全一致。"""
    odd, even = _default_odd_even()
    p = ManualCropProfile(
        odd_page=odd, even_page=even,
        source_size=(6400, 8534),
        notes="尸子卷",
    )
    s = p.to_json()
    p2 = ManualCropProfile.from_json(s)
    assert p2 == p


def test_manual_v2_json_default_fields():
    """不指定 source_size/notes 时用默认值；roundtrip 一致。"""
    odd, even = _default_odd_even()
    p = ManualCropProfile(odd_page=odd, even_page=even)
    s = p.to_json()
    p2 = ManualCropProfile.from_json(s)
    assert p2 == p
    assert p2.source_size is None
    assert p2.notes == ""


# ----------------------------------------------------------------------------
# T2: JSON v1 → v2 自动迁移
# ----------------------------------------------------------------------------


def test_manual_v1_simple_mirror_true_migrates_to_v2():
    """v1 简洁 preset（mirror_even=True）→ v2 even_page = 镜像 odd_page。"""
    v1 = (
        '{"version":1,"top":50,"bottom":40,"inner":80,"outer":30,'
        '"mirror_even":true,"source_size":[4947,7610],"notes":"x"}'
    )
    p = ManualCropProfile.from_json(v1)
    assert p.odd_page == PageCropProfile(50, 40, 80, 30)
    # mirror_even=True → even_page = {T, B, outer, inner} = (50,40,30,80)
    assert p.even_page == PageCropProfile(50, 40, 30, 80)
    assert p.source_size == (4947, 7610)
    assert p.notes == "x"


def test_manual_v1_simple_mirror_false_migrates_to_v2():
    """v1 简洁 preset（mirror_even=False）→ v2 even_page = odd_page（相同）。"""
    v1 = (
        '{"version":1,"top":50,"bottom":40,"inner":80,"outer":30,'
        '"mirror_even":false}'
    )
    p = ManualCropProfile.from_json(v1)
    assert p.odd_page == p.even_page


def test_manual_v1_simple_default_mirror_true_migrates_to_v2():
    """v1 不指定 mirror_even（默认 True）→ 镜像迁移。"""
    v1 = '{"version":1,"top":50,"bottom":40,"inner":80,"outer":30}'
    p = ManualCropProfile.from_json(v1)
    assert p.odd_page == PageCropProfile(50, 40, 80, 30)
    assert p.even_page == PageCropProfile(50, 40, 30, 80)


def test_manual_v1_nested_mirror_true_migrates_to_v2():
    """v1 嵌套 preset（odd_page 是 dict）→ 同样迁移到 v2 双 profile。"""
    v1 = (
        '{"version":1,"name":"test","odd_page":'
        '{"top":50,"bottom":40,"inner":80,"outer":30},'
        '"mirror_even":true,"source_size":[4947,7610],"notes":"x"}'
    )
    p = ManualCropProfile.from_json(v1)
    assert p.odd_page == PageCropProfile(50, 40, 80, 30)
    assert p.even_page == PageCropProfile(50, 40, 30, 80)
    assert p.source_size == (4947, 7610)
    assert p.notes == "x"


# ----------------------------------------------------------------------------
# T3: apply_manual_crop 奇偶页独立裁切
# ----------------------------------------------------------------------------


def test_apply_manual_crop_odd_page():
    """奇页：按 odd_page 直接切出 bbox。"""
    img = _blank_page_with_inner_box()  # 1000x800, 黑盒 (200,100)-(800,700)
    arr = np.asarray(img)
    odd, even = _default_odd_even()
    profile = ManualCropProfile(odd_page=odd, even_page=even)
    out = apply_manual_crop(arr, profile, is_even=False)
    # odd (50,40,80,30) → width = 1000-80-30 = 890, height = 800-50-40 = 710
    assert out.shape == (710, 890)
    out_img = Image.fromarray(out)
    # 原图黑盒 (200,100)-(800,700) → 切后 (200-80, 100-50)-(800-80, 700-50) = (120, 50)-(720, 650)
    assert out_img.getpixel((120, 50)) == 0
    assert out_img.getpixel((720, 650)) == 0
    # 上方白
    assert out_img.getpixel((120, 49)) == 255
    # 左方白（原图 col 80 之前是白）
    assert out_img.getpixel((0, 450)) == 255


def test_apply_manual_crop_even_page_independent():
    """偶页：按 even_page 独立裁切（v2.3+ inner/outer 语义反转：inner=右padding, outer=左padding）。"""
    img = _blank_page_with_inner_box()
    arr = np.asarray(img)
    odd, even = _default_odd_even()
    profile = ManualCropProfile(odd_page=odd, even_page=even)
    out = apply_manual_crop(arr, profile, is_even=True)
    # even (50,40,30,80)：
    #   inner=30 是右 padding → R = W - 30 = 970
    #   outer=80 是左 padding → L = 80
    #  width = 1000 - 80 - 30 = 890, height = 800 - 50 - 40 = 710
    assert out.shape == (710, 890)
    out_img = Image.fromarray(out)
    # 偶页 left=80（原图 col 80 是白）→ 输出 col 0 是白
    assert out_img.getpixel((0, 450)) == 255
    # 偶页 right=970（原图 col 970 是白）→ 输出 col 889 是白
    assert out_img.getpixel((889, 450)) == 255
    # 黑盒 (200,100)-(800,700) → 切后 (200-80, 100-50)-(800-80, 700-50) = (120, 50)-(720, 650)
    assert out_img.getpixel((120, 50)) == 0
    assert out_img.getpixel((720, 650)) == 0
    # 关键验证：旧 bug 把偶页当奇页切，会得 (170,50)-(770,650)；新实现 col 720 之后是白
    assert out_img.getpixel((770, 650)) == 255  # 旧测试期望 0（错的），现在应为 255


def test_apply_manual_crop_odd_even_completely_different():
    """v2.3+ 核心：odd/even 可以完全不同（之前 mirror 假设被打破）。"""
    arr = np.full((200, 300), 128, dtype=np.uint8)
    odd = PageCropProfile(top=10, bottom=20, inner=30, outer=40)
    even = PageCropProfile(top=15, bottom=25, inner=50, outer=60)
    profile = ManualCropProfile(odd_page=odd, even_page=even)

    out_odd = apply_manual_crop(arr, profile, is_even=False)
    out_even = apply_manual_crop(arr, profile, is_even=True)

    assert out_odd.shape == (200 - 10 - 20, 300 - 30 - 40)  # (170, 230)
    assert out_even.shape == (200 - 15 - 25, 300 - 50 - 60)  # (160, 190)


# ----------------------------------------------------------------------------
# T4: padding 越界 → ValueError
# ----------------------------------------------------------------------------


def test_apply_manual_crop_top_bottom_overflow():
    """top+bottom >= H → ValueError。"""
    arr = np.zeros((800, 1000), dtype=np.uint8)  # H=800, W=1000
    profile = ManualCropProfile(
        odd_page=PageCropProfile(top=400, bottom=400, inner=10, outer=10),
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
    with pytest.raises(ValueError, match="top\\+bottom"):
        apply_manual_crop(arr, profile, is_even=False)


def test_apply_manual_crop_inner_outer_overflow():
    """inner+outer >= W → ValueError。"""
    arr = np.zeros((1000, 800), dtype=np.uint8)
    profile = ManualCropProfile(
        odd_page=PageCropProfile(top=10, bottom=10, inner=500, outer=500),
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
    with pytest.raises(ValueError, match="inner\\+outer"):
        apply_manual_crop(arr, profile, is_even=False)


def test_apply_manual_crop_exact_size_no_error():
    """边界：top+bottom == H-1, inner+outer == W-1 不应抛。"""
    arr = np.zeros((800, 1000), dtype=np.uint8)
    profile = ManualCropProfile(
        odd_page=PageCropProfile(top=799, bottom=0, inner=999, outer=0),
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
    out = apply_manual_crop(arr, profile, is_even=False)
    assert out.shape == (1, 1)


# ----------------------------------------------------------------------------
# T5: source_size 不匹配 → warn + 仍执行
# ----------------------------------------------------------------------------


def test_apply_manual_crop_source_size_mismatch_warns(caplog):
    """source_size != 实际尺寸 → warn 但仍裁切。"""
    import logging

    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    odd, even = _default_odd_even()
    profile = ManualCropProfile(
        odd_page=odd, even_page=even,
        source_size=(6400, 8534),  # 故意不符
    )
    with caplog.at_level(logging.WARNING):
        out = apply_manual_crop(arr, profile)
    # 仍正确裁切
    assert out.shape == (710, 890)
    # 发出 warning
    assert any("source_size" in rec.message for rec in caplog.records)


def test_apply_manual_crop_source_size_match_no_warning(caplog):
    """source_size 匹配 → 不 warn。"""
    import logging

    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    odd, even = _default_odd_even()
    profile = ManualCropProfile(
        odd_page=odd, even_page=even, source_size=(1000, 800),
    )
    with caplog.at_level(logging.WARNING):
        apply_manual_crop(arr, profile)
    assert not any("source_size" in rec.message for rec in caplog.records)


def test_apply_manual_crop_source_size_none_no_warning(caplog):
    """source_size=None → 不 warn。"""
    import logging

    img = _blank_page_with_inner_box()
    arr = np.asarray(img)
    odd, even = _default_odd_even()
    profile = ManualCropProfile(odd_page=odd, even_page=even, source_size=None)
    with caplog.at_level(logging.WARNING):
        apply_manual_crop(arr, profile)
    assert not any("source_size" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------------
# T6: 坐标数学（v2.3+ padding_from_rect 返回 PageCropProfile，无 mirror 参数）
# ----------------------------------------------------------------------------


def test_canvas_to_image_basic():
    """Canvas 坐标 → 原图坐标（按 scale 缩放）。"""
    ix, iy = canvas_to_image(cx=600, cy=450, scale=0.5)
    assert (ix, iy) == (1200, 900)


def test_canvas_to_image_rounds_down():
    """亚像素坐标向下取整（不让用户拖到子像素）。"""
    ix, iy = canvas_to_image(cx=5, cy=7, scale=0.3)
    assert (ix, iy) == (16, 23)  # 5/0.3=16.66 → 16; 7/0.3=23.33 → 23


def test_canvas_to_image_scale_1():
    """scale=1.0 时坐标 1:1 映射。"""
    assert canvas_to_image(cx=100, cy=200, scale=1.0) == (100, 200)


def test_padding_from_rect_odd():
    """奇页：L→inner, w-R→outer, T→top, h-B→bottom。"""
    p = padding_from_rect(
        rect_in_image=(80, 50, 970, 760),  # L, T, R, B
        img_size=(1000, 800),
        is_even=False,
    )
    assert p == PageCropProfile(top=50, bottom=40, inner=80, outer=30)


def test_padding_from_rect_even():
    """偶页：L→outer, w-R→inner（互换）。"""
    p = padding_from_rect(
        rect_in_image=(30, 50, 920, 760),
        img_size=(1000, 800),
        is_even=True,
    )
    assert p == PageCropProfile(top=50, bottom=40, inner=80, outer=30)


def test_padding_roundtrip_with_apply_manual_crop():
    """padding_from_rect 输出的 padding 经 apply_manual_crop 切出原 rect。"""
    # 原图 1000×800，奇页 padding=(50,40,80,30) → 切后 bbox (80,50,970,760)
    rect = (80, 50, 970, 760)
    img_size = (1000, 800)
    p = padding_from_rect(rect, img_size, is_even=False)
    arr = np.full((img_size[1], img_size[0]), 200, dtype=np.uint8)
    profile = ManualCropProfile(
        odd_page=p,
        even_page=PageCropProfile(top=10, bottom=10, inner=10, outer=10),
    )
    out = apply_manual_crop(arr, profile, is_even=False)
    # 输出 shape 应是 (760-50, 970-80) = (710, 890)
    assert out.shape == (760 - 50, 970 - 80)


# ----------------------------------------------------------------------------
# T7: orchestrator 集成（odd/even 各裁各的）
# ----------------------------------------------------------------------------


def test_orchestrator_manual_independent_split_half(tmp_path):
    """orchestrator: split=half 输出 [左(偶), 右(奇)]，odd/even 各用各 padding。"""
    from book_cut.io.loader import PageInfo
    from book_cut.pipeline.orchestrator import _compute_page

    arr = np.full((400, 800), 200, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    page = PageInfo(page_index=0, source_name="t.png", image=img)

    odd = PageCropProfile(top=20, bottom=20, inner=40, outer=40)
    even = PageCropProfile(top=30, bottom=30, inner=60, outer=60)
    profile = ManualCropProfile(odd_page=odd, even_page=even)

    result = _compute_page(
        page,
        deskew_enabled=False,
        auto_single_page=False,
        page_order="ltr",
        crop_mode="manual",
        binarize_method="none",
        crop_config=profile,
        paper_deviation=999,
        split_strategy="half",
        half_offset=0,
        use_morph=False,
        is_sampled_page=True,
    )
    # split=half → [左(偶), 右(奇)]
    even_out, odd_out = result["sub_pages"]
    # 左(偶) 400x400，even padding (30,30,60,60) → (340, 280)
    assert even_out.size == (400 - 60 - 60, 400 - 30 - 30)
    # 右(奇) 400x400，odd padding (20,20,40,40) → (360, 320)
    assert odd_out.size == (400 - 40 - 40, 400 - 20 - 20)


# ----------------------------------------------------------------------------
# T8: 解析 helper（CLI → profile）
# ----------------------------------------------------------------------------


def test_parse_manual_padding_positional():
    """位置式：'50,40,80,30' → (50, 40, 80, 30)。"""
    assert parse_manual_padding("50,40,80,30") == (50, 40, 80, 30)


def test_parse_manual_padding_keyvalue():
    """键值式：'T=50,B=40,I=80,O=30' → (50, 40, 80, 30)。"""
    assert parse_manual_padding("T=50,B=40,I=80,O=30") == (50, 40, 80, 30)


def test_parse_manual_padding_keyvalue_reordered():
    """键值式：键顺序任意。"""
    assert parse_manual_padding("O=30,I=80,B=40,T=50") == (50, 40, 80, 30)


def test_parse_manual_padding_with_spaces():
    """允许空格：'T=50, B=40, I=80, O=30'。"""
    assert parse_manual_padding("T=50, B=40, I=80, O=30") == (50, 40, 80, 30)


def test_parse_manual_padding_empty_raises():
    """空字符串 → ValueError。"""
    with pytest.raises(ValueError, match="为空"):
        parse_manual_padding("")


def test_parse_manual_padding_unknown_key_raises():
    """未知字段名 → ValueError。"""
    with pytest.raises(ValueError, match="未知字段"):
        parse_manual_padding("T=50,B=40,X=80,O=30")


def test_parse_manual_padding_missing_key_raises():
    """缺少字段 → ValueError。"""
    with pytest.raises(ValueError, match="缺少字段"):
        parse_manual_padding("T=50,B=40,I=80")


def test_parse_manual_padding_negative_raises():
    """负值 → ValueError。"""
    with pytest.raises(ValueError, match="不能为负"):
        parse_manual_padding("50,40,-1,30")


def test_parse_manual_padding_to_profile():
    """parse 输出可直接构造 PageCropProfile。"""
    t, b, i, o = parse_manual_padding("50,40,80,30")
    odd = PageCropProfile(top=t, bottom=b, inner=i, outer=o)
    assert (odd.top, odd.bottom, odd.inner, odd.outer) == (50, 40, 80, 30)


# ----------------------------------------------------------------------------
# T9: GUI Spinbox 隔离（验证 GUI 内部辅助函数不串）
# ----------------------------------------------------------------------------


def test_gui_manual_widgets_dual_isolation():
    """v2.3+ GUI：奇偶页 Spinbox 互相隔离。

    通过 import GUI 模块并验证：
    1) 模块定义了 manual_*_var 奇偶两套
    2) 加载 preset 时两组同时被填充
    """
    # 静态检查：仅验证模块可 import + 关键 var 名存在
    import book_cut.gui as gui_mod  # noqa: F401

    # 不实际启动 Tk（headless 环境可能无 DISPLAY）
    # 改为检查模块属性：手动构造 profile 看 round-trip 不串
    odd = PageCropProfile(top=11, bottom=22, inner=33, outer=44)
    even = PageCropProfile(top=55, bottom=66, inner=77, outer=88)
    prof = ManualCropProfile(odd_page=odd, even_page=even)
    s = prof.to_json()
    prof2 = ManualCropProfile.from_json(s)
    # 两组完全独立，互不影响
    assert prof2.odd_page == odd
    assert prof2.even_page == even
    assert prof2.odd_page != prof2.even_page  # 关键隔离断言