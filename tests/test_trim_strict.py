"""v2.1 trim B 方案：``--trim-strict`` 排除页眉/页脚稀疏行。

场景：A+B（``--trim-source binarized`` + ``--trim-min-component-ratio``）会把页眉/页脚的
小字符也纳入 bbox（rows 1700-1850 / 7557-7610），用户希望像早期版本那样只保留主体正文。
方案 B 加 ``strict=True`` 后置过滤：剔除 ink 密度低于阈值的稀疏行。

TDD：先写 RED（参数不存在 → TypeError），再 GREEN。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from book_cut.detect.trim import trim_margins

# ----------------------------------------------------------------------------
# 合成 fixture
# ----------------------------------------------------------------------------


def _synth_page_with_header_and_footer() -> Image.Image:
    """1000×800 白纸：
    - 页眉：rows 50-100，每行 1 个 8×10 小块（area=80 = min_area，刚过 CCA）
      → per-row ink = 80，max_row_ink × 0.1 = 90 → strict 阈值 90 → 排除 ✓
    - 主体正文：rows 200-700 实心矩形（per-row ink = 900）→ 保留
    - 页脚：rows 720-770，每行 1 个 8×10 小块（同页眉）→ strict 排除 ✓
    - 左右版框线：x=10-15 / x=985-990（5×800，aspect 160）→ CCA 滤

    设计要点：use_morph=True 时 MORPH_OPEN 会清掉 1×1 噪点。所以页眉/页脚用 8×10
    矩形（area=80）才能跨过 morph + min_area 双门槛。per-row ink=80 < strict_threshold=90。
    """
    img = Image.new("RGB", (1000, 800), "white")
    draw = ImageDraw.Draw(img)
    # 左版框线（aspect 160 → CCA 滤）
    draw.rectangle([(10, 0), (15, 800)], fill="black")
    # 右版框线
    draw.rectangle([(985, 0), (990, 800)], fill="black")
    # 页眉稀疏小字符（每行 1 个 8×10 小块，per-row ink = 80）
    for y in range(50, 100):
        draw.rectangle([(500, y), (508, y + 10)], fill="black")
    # 主体正文（实心矩形，per-row ink = 900）
    draw.rectangle([(50, 200), (950, 700)], fill="black")
    # 页脚稀疏小字符（同页眉）
    for y in range(720, 770):
        draw.rectangle([(500, y), (508, y + 10)], fill="black")
    return img


def _synth_page_pure_text() -> Image.Image:
    """1000×800 纯正文（无页眉页脚）→ strict 不影响。

    主体实心矩形 rows 50-750（per-row ink = 900）。
    strict 阈值 = max(50, 90) = 90，每行 ink = 900 ≥ 90 → 全保留。
    """
    img = Image.new("RGB", (1000, 800), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(50, 50), (950, 750)], fill="black")
    return img


# ----------------------------------------------------------------------------
# 私有/公共 API：trim_margins 支持 strict
# ----------------------------------------------------------------------------


def test_trim_margins_accepts_strict_kwarg() -> None:
    """``trim_margins`` 公共 API 支持 ``strict: bool``。

    RED: 当前签名不接受 strict → TypeError。
    """
    img = _synth_page_pure_text()
    # 不应抛 TypeError
    out = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
        strict=True,
    )
    assert out is not None
    assert isinstance(out, Image.Image)


def test_trim_strict_excludes_sparse_header_and_footer() -> None:
    """``strict=True`` 排除页眉/页脚的稀疏行（与不带 strict 对比 bbox 更紧）。

    合成图：rows 50-100 sparse + rows 200-700 dense + rows 720-770 sparse
    不带 strict：bbox 包含 rows 50-100 + 720-770（H ≈ 720）
    带 strict：bbox 只包含 rows 200-700（H ≈ 500）
    """
    img = _synth_page_with_header_and_footer()
    out_normal = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
    )
    out_strict = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
        strict=True,
    )
    # strict 输出 H 应明显小于 normal（H_strict < 0.85 × H_normal）
    assert out_strict.size[1] < out_normal.size[1] * 0.85, (
        f"strict 应排除稀疏页眉/页脚，但 strict H={out_strict.size[1]} "
        f"vs normal H={out_normal.size[1]}"
    )


def test_trim_strict_no_op_on_pure_text() -> None:
    """``strict=True`` 对纯正文（无稀疏行）几乎不影响 bbox。"""
    img = _synth_page_pure_text()
    out_normal = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
    )
    out_strict = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
        strict=True,
    )
    # 输出 H 差距应 < 100 px（允许少量 partial-row 误差）
    delta = abs(out_strict.size[1] - out_normal.size[1])
    assert delta < 100, (
        f"strict 对纯正文不应有大影响，但 ΔH={delta} "
        f"(normal={out_normal.size[1]}, strict={out_strict.size[1]})"
    )


def test_trim_strict_default_false_no_change() -> None:
    """``strict`` 默认 False → 行为与 v2.1 A+B 一致（向后兼容）。"""
    img = _synth_page_with_header_and_footer()
    out_default = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
    )
    out_explicit_false = trim_margins(
        img,
        trim_source="binarized",
        min_component_ratio=0.0001,
        strict=False,
    )
    assert out_default.size == out_explicit_false.size, (
        f"strict=False 应与不传一致: default={out_default.size} "
        f"vs explicit={out_explicit_false.size}"
    )


# ----------------------------------------------------------------------------
# 真实样本：尸子图
# ----------------------------------------------------------------------------


@pytest.fixture()
def shizi_sample_path() -> str:
    sample = Path(__file__).resolve().parent.parent / "samples" / "尸子卷上下.浙江书局.光绪三年刊_0021.png"
    if not sample.exists():
        pytest.skip(f"尸子样本不存在: {sample}")
    return str(sample)


def test_trim_strict_tightens_shizi_bbox(shizi_sample_path: str) -> None:
    """尸子图 + ``strict=True`` → 输出 H 应 < A+B 默认。

    尸子图 6400×8534：
    - A+B 默认：H ≈ 5910（rows 1700-7610，含页眉 rows 1700-1849 + 页脚 7557-7610）
    - A+B + strict：H 应更紧（rows 1850-7557 类似参考图 5707）

    验证：strict 输出 H < normal 输出 H。
    """
    img = Image.open(shizi_sample_path)
    out_normal = trim_margins(
        img,
        padding=0,
        extra_padding=0,
        trim_source="binarized",
        min_component_ratio=0.0001,
        horizontal=False,
    )
    out_strict = trim_margins(
        img,
        padding=0,
        extra_padding=0,
        trim_source="binarized",
        min_component_ratio=0.0001,
        horizontal=False,
        strict=True,
    )
    # strict 输出 H 应 < normal（页眉/页脚排除）
    assert out_strict.size[1] < out_normal.size[1], (
        f"strict 应让 bbox 更紧: strict H={out_strict.size[1]} "
        f"vs normal H={out_normal.size[1]}"
    )


# ----------------------------------------------------------------------------
# CLI flag：--trim-strict
# ----------------------------------------------------------------------------


def test_cli_trim_strict_flag_accepted() -> None:
    """``--trim-strict`` flag 存在（v2.1+ B 方案）。"""
    _ROOT = Path(__file__).resolve().parent.parent
    _SRC = _ROOT / "src"
    _ENV = {**os.environ, "PYTHONPATH": str(_SRC)}

    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-strict" in result.stdout, (
        "--trim-strict flag 应存在，但 help 文本中未找到"
    )
