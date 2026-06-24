"""v2.2 manual crop 测试：ManualCropProfile + apply_manual_crop + coord math。

对应提案：``docs/dev/2026-06-24-v2.2-manual-crop.md`` §7

TDD 约定：先写 RED（模块/函数不存在 → ImportError/AttributeError），再实现 GREEN。
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from book_cut.detect.manual import (
    ManualCropProfile,
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


# ----------------------------------------------------------------------------
# T1: ManualCropProfile JSON roundtrip
# ----------------------------------------------------------------------------


def test_manual_crop_profile_json_roundtrip():
    """profile → JSON → profile 应当完全一致。"""
    p = ManualCropProfile(
        top=50,
        bottom=40,
        inner=80,
        outer=30,
        mirror_even=True,
        source_size=(6400, 8534),
        notes="尸子卷",
    )
    s = p.to_json()
    p2 = ManualCropProfile.from_json(s)
    assert p2 == p


def test_manual_crop_profile_json_default_fields():
    """不指定 mirror_even/source_size/notes 时用默认值；roundtrip 一致。"""
    p = ManualCropProfile(top=10, bottom=20, inner=30, outer=40)
    s = p.to_json()
    p2 = ManualCropProfile.from_json(s)
    assert p2 == p
    assert p2.mirror_even is True
    assert p2.source_size is None
    assert p2.notes == ""


def test_manual_crop_profile_json_nested_odd_page():
    """v2.2 嵌套 schema：``{"odd_page": {...}}`` 也能解析。"""
    nested = (
        '{"version":1,"name":"test","odd_page":'
        '{"top":50,"bottom":40,"inner":80,"outer":30},'
        '"mirror_even":true,"source_size":[4947,7610],"notes":"x"}'
    )
    p = ManualCropProfile.from_json(nested)
    assert p.top == 50
    assert p.bottom == 40
    assert p.inner == 80
    assert p.outer == 30
    assert p.mirror_even is True
    assert p.source_size == (4947, 7610)
    assert p.notes == "x"


# ----------------------------------------------------------------------------
# T2: apply_manual_crop 奇页
# ----------------------------------------------------------------------------


def test_apply_manual_crop_odd_page():
    """奇页：不镜像，按 T/B/I/O 直接切出 bbox。"""
    img = _blank_page_with_inner_box()  # 1000x800, 黑盒 (200,100)-(800,700)
    arr = np.asarray(img)
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30, mirror_even=False
    )
    out = apply_manual_crop(arr, profile, is_even=False)
    # expected: width = 1000-80-30 = 890, height = 800-50-40 = 710
    assert out.shape == (710, 890)
    # 原图黑盒 (200,100)-(800,700) → 切后 (200-80, 100-50)-(800-80, 700-50) = (120, 50)-(720, 650)
    out_img = Image.fromarray(out)
    # 取 4 个采样点验证
    # 原图 (200,100) = 黑 → 切后 (120,50) = 黑
    assert out_img.getpixel((120, 50)) == 0
    # 原图 (800,700) = 黑 → 切后 (720,650) = 黑
    assert out_img.getpixel((720, 650)) == 0
    # 原图 (200,99) = 白（黑盒上方）→ 切后 (120,49) = 白
    assert out_img.getpixel((120, 49)) == 255
    # 原图 (79,500) = 白（黑盒左边）→ 切后 (-1,450) 不在范围内
    # 取 (0, 450) 应为白（原图 col 80 是白）
    assert out_img.getpixel((0, 450)) == 255


# ----------------------------------------------------------------------------
# T3: apply_manual_crop 偶页镜像
# ----------------------------------------------------------------------------


def test_apply_manual_crop_even_page_mirror():
    """偶页：mirror_even=True 时 inner↔outer 互换。

    odd profile T=50, B=40, I=80, O=30：
    - 奇页：left=80, right=1000-30=970
    - 偶页：left=30, right=1000-80=920
    """
    img = _blank_page_with_inner_box()
    arr = np.asarray(img)
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30, mirror_even=True
    )
    out = apply_manual_crop(arr, profile, is_even=True)
    assert out.shape == (710, 890)
    out_img = Image.fromarray(out)
    # 偶页 left=30：原图 col 30 是白（黑盒从 col 200 开始）
    assert out_img.getpixel((0, 450)) == 255
    # 偶页 right=920：原图 col 920 是白（黑盒到 col 800）
    assert out_img.getpixel((889, 450)) == 255
    # 黑盒在原图 (200,100)-(800,700) → 切后 (200-30, 100-50)-(800-30, 700-50) = (170, 50)-(770, 650)
    assert out_img.getpixel((170, 50)) == 0
    assert out_img.getpixel((770, 650)) == 0


def test_apply_manual_crop_even_page_no_mirror():
    """偶页 + mirror_even=False：与奇页同效（不镜像）。"""
    img = _blank_page_with_inner_box()
    arr = np.asarray(img)
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30, mirror_even=False
    )
    out = apply_manual_crop(arr, profile, is_even=True)
    # 与奇页同 bbox：(80, 50)-(970, 760)
    assert out.shape == (710, 890)
    out_img = Image.fromarray(out)
    # 黑盒 (200,100)-(800,700) → (120, 50)-(720, 650)
    assert out_img.getpixel((120, 50)) == 0
    assert out_img.getpixel((720, 650)) == 0


# ----------------------------------------------------------------------------
# T4: padding 越界 → ValueError
# ----------------------------------------------------------------------------


def test_apply_manual_crop_top_bottom_overflow():
    """top+bottom >= H → ValueError。"""
    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    profile = ManualCropProfile(top=400, bottom=400, inner=10, outer=10)
    with pytest.raises(ValueError, match="top\\+bottom"):
        apply_manual_crop(arr, profile)


def test_apply_manual_crop_inner_outer_overflow():
    """inner+outer >= W → ValueError。"""
    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    profile = ManualCropProfile(top=10, bottom=10, inner=500, outer=500)
    with pytest.raises(ValueError, match="inner\\+outer"):
        apply_manual_crop(arr, profile)


def test_apply_manual_crop_exact_size_no_error():
    """边界：top+bottom == H-1, inner+outer == W-1 不应抛。"""
    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    # 799+1 == 800 → 不抛；output 1x1
    profile = ManualCropProfile(top=799, bottom=0, inner=999, outer=0)
    out = apply_manual_crop(arr, profile)
    assert out.shape == (1, 1)


# ----------------------------------------------------------------------------
# T5: source_size 不匹配 → warn + 仍执行
# ----------------------------------------------------------------------------


def test_apply_manual_crop_source_size_mismatch_warns(caplog):
    """source_size != 实际尺寸 → warn 但仍裁切。"""
    import logging

    img = _blank_page_with_inner_box()  # 1000x800
    arr = np.asarray(img)
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30,
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
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30,
        source_size=(1000, 800),
    )
    with caplog.at_level(logging.WARNING):
        apply_manual_crop(arr, profile)
    assert not any("source_size" in rec.message for rec in caplog.records)


def test_apply_manual_crop_source_size_none_no_warning(caplog):
    """source_size=None → 不 warn。"""
    import logging

    img = _blank_page_with_inner_box()
    arr = np.asarray(img)
    profile = ManualCropProfile(
        top=50, bottom=40, inner=80, outer=30, source_size=None
    )
    with caplog.at_level(logging.WARNING):
        apply_manual_crop(arr, profile)
    assert not any("source_size" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------------
# T9: 坐标数学（纯函数，与 GUI 解耦）
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
    top, bottom, inner, outer = padding_from_rect(
        rect_in_image=(80, 50, 970, 760),  # L, T, R, B
        img_size=(1000, 800),
        is_even=False,
        mirror_even=True,
    )
    assert (top, bottom, inner, outer) == (50, 40, 80, 30)


def test_padding_from_rect_even_mirror():
    """偶页 + mirror=True：L→outer, w-R→inner（互换）。"""
    top, bottom, inner, outer = padding_from_rect(
        rect_in_image=(30, 50, 920, 760),
        img_size=(1000, 800),
        is_even=True,
        mirror_even=True,
    )
    assert (top, bottom, inner, outer) == (50, 40, 80, 30)


def test_padding_from_rect_even_no_mirror():
    """偶页 + mirror=False：与奇页同效。"""
    top, bottom, inner, outer = padding_from_rect(
        rect_in_image=(80, 50, 970, 760),
        img_size=(1000, 800),
        is_even=True,
        mirror_even=False,
    )
    assert (top, bottom, inner, outer) == (50, 40, 80, 30)


def test_padding_roundtrip_with_apply_manual_crop():
    """padding_from_rect 输出的 padding 经 apply_manual_crop 切出原 rect。"""
    # 原图 1000×800，奇页 padding=(50,40,80,30) → 切后 bbox (80,50,970,760)
    rect = (80, 50, 970, 760)
    img_size = (1000, 800)
    t, b, i, o = padding_from_rect(rect, img_size, is_even=False, mirror_even=True)
    profile = ManualCropProfile(top=t, bottom=b, inner=i, outer=o)
    arr = np.full((img_size[1], img_size[0]), 200, dtype=np.uint8)
    out = apply_manual_crop(arr, profile, is_even=False)
    # 输出 shape 应是 (970-80, 760-50) = (890, 710)
    assert out.shape == (760 - 50, 970 - 80)


# ----------------------------------------------------------------------------
# 解析 helper（v2.2+ CLI → profile）
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
    """parse 输出可直接构造 ManualCropProfile。"""
    t, b, i, o = parse_manual_padding("50,40,80,30")
    p = ManualCropProfile(top=t, bottom=b, inner=i, outer=o)
    assert (p.top, p.bottom, p.inner, p.outer) == (50, 40, 80, 30)
