"""切分策略测试。"""

from __future__ import annotations

from PIL import Image

from book_cut.split.border import find_border_split
from book_cut.split.gutter import find_gutter_column
from book_cut.split.half import split_half


def test_split_half(two_page_image):
    pages = split_half(two_page_image)
    left, right = pages[0], pages[1]
    assert len(pages) == 2
    assert left.size[0] == 400
    assert right.size[0] == 400
    assert left.size == right.size


def test_split_half_offset(two_page_image):
    pages = split_half(two_page_image, offset=20)
    left, right = pages[0], pages[1]
    assert left.size[0] == 420
    assert right.size[0] == 380


def test_gutter_finds_white_gap(two_page_image):
    x = find_gutter_column(two_page_image, search_range=0.4)
    # 中缝白色区在 380~420 内，任意值都应落在该区间
    assert 380 <= x <= 420


def test_gutter_split_dimensions(two_page_image):
    from book_cut.split.gutter import split_gutter

    pages = split_gutter(two_page_image)
    assert len(pages) == 2
    left, right = pages[0], pages[1]
    assert left.size[1] == right.size[1] == 500
    assert left.size[0] + right.size[0] == 800


def test_gutter_detects_single_page():
    """单页扫描（一边几乎全白）应只输出 1 张图。"""
    import numpy as np
    from PIL import Image

    from book_cut.split.gutter import split_gutter

    # 800x500：左边全白，右边有墨迹
    arr = np.full((500, 800, 3), 255, dtype=np.uint8)
    arr[100:400, 500:780] = 0
    img = Image.fromarray(arr)

    pages = split_gutter(img)
    assert len(pages) == 1
    assert pages[0].size == img.size


def test_gutter_can_disable_single_page_detection():
    """关闭 auto_single_page 后强制对半切。"""
    import numpy as np
    from PIL import Image

    from book_cut.split.gutter import split_gutter

    arr = np.full((500, 800, 3), 255, dtype=np.uint8)
    arr[100:400, 500:780] = 0
    img = Image.fromarray(arr)

    pages = split_gutter(img, auto_single_page=False)
    assert len(pages) == 2


def test_is_single_page_helper():
    """is_single_page 直接测试。"""
    import numpy as np
    from PIL import Image

    from book_cut.detect.single_page import is_single_page

    # 白底 + 两边都有墨迹（双页）
    arr = np.full((100, 200, 3), 255, dtype=np.uint8)
    arr[20:80, 20:90] = 0
    arr[20:80, 110:180] = 0
    assert not is_single_page(Image.fromarray(arr), gutter_x=100)

    # 白底 + 只有左侧有墨迹（单页）
    arr2 = np.full((100, 200, 3), 255, dtype=np.uint8)
    arr2[20:80, 20:90] = 0
    assert is_single_page(Image.fromarray(arr2), gutter_x=100)


def test_border_finds_outer_rect(two_page_image_with_border):
    x = find_border_split(two_page_image_with_border)
    # 两版框 x 范围 [80, 380] ∪ [420, 720]，整体中点 ≈ 400
    assert x is not None
    assert 350 <= x <= 450


def test_half_on_small_image_fails():
    tiny = Image.new("RGB", (1, 100), "white")
    import pytest

    from book_cut.split.half import split_half

    with pytest.raises(ValueError):
        split_half(tiny)
