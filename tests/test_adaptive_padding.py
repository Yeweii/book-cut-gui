"""v2.1+ 测试：``--adaptive-padding N`` 覆盖 adaptive 公式。

默认行为（无 flag）= v1.9 公式（min(h,w) * 0.02）。
设值后 = N 像素（opt-in）。
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from book_cut.detect.paper import CropConfig, default_crop_config
from book_cut.detect.trim import _trim_margins_from_array, trim_margins


def _page_with_content_and_padding() -> Image.Image:
    """2000×2000 白纸，中央 1000×1000 文字区（远离边界 500 px）。"""
    img = Image.new("RGB", (2000, 2000), "white")
    # 中央 1000×1000 内容 (从 500,500 到 1500,1500)
    for y in range(500, 1500, 30):
        for x in range(500, 1500, 5):
            img.putpixel((x, y), 0)
    return img


# ----------------------------------------------------------------------------
# 直接调 trim_margins（传 config.padding override）
# ----------------------------------------------------------------------------


def test_adaptive_padding_override_shrinks_output() -> None:
    """config.padding=N 应使输出比默认 adaptive 小。

    默认 min(2000, 2000) * 0.02 = 40 px；override=10 应让输出更紧。
    """
    img = _page_with_content_and_padding()
    # 用 config.padding=40（模拟默认）
    cfg_default = default_crop_config(paper_color=240.0)
    out_default = trim_margins(img, config=cfg_default)
    # 用 config.padding=10（override）
    cfg_tight = CropConfig(paper_color=240.0, padding=10)
    out_tight = trim_margins(img, config=cfg_tight)
    # tight 输出应比 default 输出更小（每边少 30 px → 总共少 60）
    assert out_tight.size[0] <= out_default.size[0]
    assert out_tight.size[1] <= out_default.size[1]
    # 至少差 20 px 一边
    assert (out_default.size[0] - out_tight.size[0]) >= 20
    assert (out_default.size[1] - out_tight.size[1]) >= 20


def test_adaptive_padding_override_in_from_array() -> None:
    """私有 API 也支持 padding override。"""
    img = _page_with_content_and_padding()
    arr = np.asarray(img.convert("L"))
    cfg_default = default_crop_config(paper_color=240.0)
    out_default = _trim_margins_from_array(arr, config=cfg_default)
    cfg_tight = CropConfig(paper_color=240.0, padding=10)
    out_tight = _trim_margins_from_array(arr, config=cfg_tight)
    assert (out_default.size[0] - out_tight.size[0]) >= 20


def test_adaptive_padding_none_means_default_formula() -> None:
    """config.padding=None 走 adaptive_padding 公式（默认行为）。"""
    img = _page_with_content_and_padding()
    cfg = CropConfig(paper_color=240.0, padding=None)
    out = trim_margins(img, config=cfg)
    # min(2000, 2000)*0.02=40 → 输出宽 = (1500-500) + 2*40 = 1080
    assert out.size[0] >= 1000  # ≥ 1000
    assert out.size[0] <= 1100  # ≤ 1100


# ----------------------------------------------------------------------------
# 真实样本：--adaptive-padding 应减小输出尺寸（保留鱼尾前提）
# ----------------------------------------------------------------------------


@pytest.fixture()
def shizi_sample_path() -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sample = root / "samples" / "尸子卷上下.浙江书局.光绪三年刊_0021.png"
    if not sample.exists():
        pytest.skip(f"尸子样本不存在: {sample}")
    return str(sample)


def test_adaptive_padding_reduces_shizi_output_with_gutter_band(
    shizi_sample_path: str,
) -> None:
    """尸子图 + gutter_band + padding override(0) → 输出 H 比默认小。

    默认 adaptive (paper_color=255) → 输出 H ≈ 7543。
    override=0 → 输出 H 应 < 7500（mask bbox 加 0 padding，节省 adaptive 占的 60+ px）。
    override 应生效（输出比默认小），且鱼尾仍保留（mask bbox 已含鱼尾）。
    """
    img = Image.open(shizi_sample_path)
    cfg_default = CropConfig(paper_color=255.0, padding=None)
    out_default = trim_margins(
        img,
        config=cfg_default,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_band=(0.35, 0.5),
    )
    cfg_tight = CropConfig(paper_color=255.0, padding=0)
    out_tight = trim_margins(
        img,
        config=cfg_tight,
        trim_source="binarized",
        min_component_ratio=0.0001,
        gutter_band=(0.35, 0.5),
    )
    # override 应让输出比默认小
    assert out_tight.size[1] < out_default.size[1], (
        f"override 后 H {out_tight.size[1]} >= default H {out_default.size[1]}"
    )
    # 至少小 30 px
    assert (out_default.size[1] - out_tight.size[1]) >= 30
    # 鱼尾仍保留（mask bbox 已含鱼尾，padding=0 不会裁掉）
    assert out_tight.size[1] >= 7400, f"output H {out_tight.size[1]} < 7400 → 鱼尾可能被裁"
