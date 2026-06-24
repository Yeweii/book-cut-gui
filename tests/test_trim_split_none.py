"""v2.1+：``--split none`` + ``--crop trim`` 行为：保留输入全宽（只裁上下）。

场景：双页扫描用户用 ``--split none``（不想拆分），但仍想 trim 上下空白。
当前 trim 默认全 bbox 裁切，丢右侧内容。需 ``horizontal=False`` 模式。
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from book_cut.detect.paper import CropConfig, default_crop_config
from book_cut.detect.trim import _trim_margins_from_array, trim_margins


def _double_page_synthetic() -> Image.Image:
    """2000×2400 白纸，左页内容 (col 100..900) + 中缝 (col 950..1050) + 右页内容 (col 1100..1900)。

    顶部留白 100px，底部留白 100px，左右各留 100px。
    """
    img = Image.new("RGB", (2000, 2400), "white")
    # 左页文字区 (col 100-900, row 100-2300)
    for y in range(100, 2300, 50):
        for x in range(100, 900, 30):
            img.putpixel((x, y), 0)
    # 右页文字区 (col 1100-1900, row 100-2300)
    for y in range(100, 2300, 50):
        for x in range(1100, 1900, 30):
            img.putpixel((x, y), 0)
    return img


# ----------------------------------------------------------------------------
# 单元测试：trim_margins / _trim_margins_from_array 加 horizontal 参数
# ----------------------------------------------------------------------------


def test_trim_default_crops_horizontally() -> None:
    """默认行为（horizontal=True）：横向也裁。"""
    img = _double_page_synthetic()
    cfg = default_crop_config(paper_color=240.0)
    out = trim_margins(img, config=cfg)
    # 输出宽 < 输入宽（裁掉了左右空白）
    assert out.size[0] < img.size[0]


def test_trim_horizontal_false_preserves_full_width() -> None:
    """horizontal=False：保留全宽，只裁上下。"""
    img = _double_page_synthetic()
    cfg = default_crop_config(paper_color=240.0)
    out = trim_margins(img, config=cfg, horizontal=False)
    # 输出宽 = 输入宽（左右没裁）
    assert out.size[0] == img.size[0], (
        f"horizontal=False 应保留全宽，实际 {out.size[0]} != input {img.size[0]}"
    )
    # 输出高 < 输入高（裁掉了上下空白）
    assert out.size[1] < img.size[1]


def test_trim_from_array_horizontal_false_preserves_full_width() -> None:
    """私有 API 也支持 horizontal=False。"""
    img = _double_page_synthetic()
    arr = np.asarray(img.convert("L"))
    cfg = default_crop_config(paper_color=240.0)
    out = _trim_margins_from_array(arr, config=cfg, horizontal=False)
    assert out.size[0] == img.size[0]


def test_trim_horizontal_false_uses_input_top_bottom() -> None:
    """horizontal=False：上下仍按 ink bbox + padding 裁切。"""
    img = _double_page_synthetic()
    cfg = CropConfig(paper_color=240.0, padding=0)
    out_default = _trim_margins_from_array(
        np.asarray(img.convert("L")), config=cfg, horizontal=True
    )
    out_vertical = _trim_margins_from_array(
        np.asarray(img.convert("L")), config=cfg, horizontal=False
    )
    # horizontal=False 输出 H 与 horizontal=True 输出 H 一致（垂直裁切逻辑相同）
    assert out_vertical.size[1] == out_default.size[1]
    # 但 horizontal=False 输出 W = 输入 W（保留全宽）
    assert out_vertical.size[0] == img.size[0]
    # 而 horizontal=True 输出 W < 输入 W
    assert out_default.size[0] < img.size[0]


# ----------------------------------------------------------------------------
# 真实样本：尸子图 0021 --split none 应保留全宽
# ----------------------------------------------------------------------------


@pytest.fixture()
def shizi_sample_path() -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sample = root / "samples" / "尸子卷上下.浙江书局.光绪三年刊_0021.png"
    if not sample.exists():
        pytest.skip(f"尸子样本不存在: {sample}")
    return str(sample)


def test_split_none_preserves_shizi_full_width(shizi_sample_path: str) -> None:
    """尸子图 + horizontal=False → 输出 W = 输入 W（保留右侧副页）。"""
    img = Image.open(shizi_sample_path)
    cfg = CropConfig(paper_color=255.0, padding=0)
    out = trim_margins(
        img,
        config=cfg,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_band=(0.35, 0.5),
        horizontal=False,
    )
    # horizontal=False 应保留全宽
    assert out.size[0] == img.size[0], (
        f"horizontal=False 应保留 W={img.size[0]}, 实际 {out.size[0]}"
    )
    # 但 H 应被裁切（小于输入 H）
    assert out.size[1] < img.size[1], (
        f"水平裁切关闭时 vertical 仍应裁切，但 H {out.size[1]} >= input {img.size[1]}"
    )
