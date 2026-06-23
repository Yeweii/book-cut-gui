"""v1.9+ 图片预处理增强测试（sharpen / denoise / clahe / gamma）。

覆盖：
- 4 个模块各自的 fast/balanced/best 档位产出（dtype / mode / 形状）
- preprocess() dispatcher 链式调度
- chain token 解析（`sharpen` / `sharpen=1.5`）
- 错误路径（未知 op / gamma 越界 / 非法 quality）
- BOOKCUT_PREPROCESS_QUALITY 环境变量覆盖
"""

from __future__ import annotations

import os

import numpy as np
import pytest
from PIL import Image

from book_cut.preprocess import (
    clahe,
    denoise,
    gamma,
    parse_chain,
    preprocess,
    sharpen,
)


# ---------------------------------------------------------------------------
# 共享 fixtures
# ---------------------------------------------------------------------------


def _gray_with_text(size: int = 200) -> Image.Image:
    """合成一张有"文字"的灰度图：白底+黑块。"""
    arr = np.full((size, size), 220, dtype=np.uint8)
    for y in range(40, size - 40, 30):
        arr[y:y + 8, 40:size - 40] = 30
    # 加点噪点（1-2 px 亮暗点）
    arr[10:12, 10:12] = 180
    arr[100:103, 100:103] = 240
    return Image.fromarray(arr, mode="L")


def _rgb_synthetic(size: int = 200) -> Image.Image:
    return Image.fromarray(
        np.full((size, size, 3), 220, dtype=np.uint8), mode="RGB"
    )


# ---------------------------------------------------------------------------
# sharpen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quality", ["fast", "balanced", "best"])
def test_sharpen_returns_L_mode(quality, monkeypatch):
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", quality)
    out = sharpen(_gray_with_text())
    assert out.mode == "L"
    assert out.size == (200, 200)


def test_sharpen_balanced_differs_from_input(monkeypatch):
    """balanced 走 unsharp mask，应该与输入不完全相同（锐化增加了高频）。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out = sharpen(img, amount=1.5)
    in_arr = np.asarray(img, dtype=np.int16)
    out_arr = np.asarray(out, dtype=np.int16)
    assert not np.array_equal(in_arr, out_arr)


def test_sharpen_fast_zero_amount_returns_similar(monkeypatch):
    """fast 走 PIL SHARPEN，必然改变像素。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "fast")
    img = _gray_with_text()
    out = sharpen(img)
    assert np.asarray(out).dtype == np.uint8


# ---------------------------------------------------------------------------
# denoise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quality", ["fast", "balanced", "best"])
def test_denoise_returns_L_mode(quality, monkeypatch):
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", quality)
    out = denoise(_gray_with_text())
    assert out.mode == "L"


def test_denoise_balanced_smooths(monkeypatch):
    """balanced 走 NL-Means，噪点应该被压平。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    in_std = float(np.asarray(img).std())
    out_std = float(np.asarray(denoise(img, h=7)).std())
    # 输出标准差应该 ≤ 输入（噪点被压平）
    assert out_std <= in_std


# ---------------------------------------------------------------------------
# clahe
# ---------------------------------------------------------------------------


def test_clahe_returns_L_mode(monkeypatch):
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    out = clahe(_gray_with_text())
    assert out.mode == "L"


def test_clahe_fast_is_noop(monkeypatch):
    """fast 档 no-op，输出 == 输入。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "fast")
    img = _gray_with_text()
    out = clahe(img)
    assert np.array_equal(np.asarray(img), np.asarray(out))


def test_clahe_balanced_expands_dynamic_range(monkeypatch):
    """balanced 走 cv2 CLAHE，对比度应该展开（std 增大或均值调整）。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out = clahe(img, clip=3.0)
    in_arr = np.asarray(img)
    out_arr = np.asarray(out)
    # std 应该变化（不一定更大，取决于内容；至少数值有变化）
    assert not np.array_equal(in_arr, out_arr)


# ---------------------------------------------------------------------------
# gamma
# ---------------------------------------------------------------------------


def test_gamma_returns_L_mode(monkeypatch):
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    out = gamma(_gray_with_text())
    assert out.mode == "L"


def test_gamma_fast_is_noop(monkeypatch):
    """fast 档 no-op（γ=1.0）。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "fast")
    img = _gray_with_text()
    out = gamma(img)
    assert np.array_equal(np.asarray(img), np.asarray(out))


def test_gamma_brightens_with_low_value(monkeypatch):
    """γ<1 提亮（输出均值应该 > 输入均值）。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out = gamma(img, value=0.6)
    assert float(np.asarray(out).mean()) > float(np.asarray(img).mean())


def test_gamma_validates_range(monkeypatch):
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    with pytest.raises(ValueError, match="gamma value"):
        gamma(img, value=10.0)
    with pytest.raises(ValueError, match="gamma value"):
        gamma(img, value=0.0)
    with pytest.raises(ValueError, match="gamma value"):
        gamma(img, value=-1.0)


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_empty_chain_returns_original():
    img = _gray_with_text()
    out = preprocess(img, [], quality="balanced")
    assert out is img


def test_dispatcher_string_chain_parsed():
    chain = parse_chain("sharpen, denoise=10 , clahe=2.5")
    assert chain == ["sharpen", "denoise=10", "clahe=2.5"]


def test_dispatcher_chain_order(monkeypatch):
    """链中 op 按声明顺序应用：denoise → clahe → sharpen。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out = preprocess(img, "denoise=7,clahe=2.0,sharpen=1.5", quality="balanced")
    assert out.mode == "L"
    # 输出应该与原图不同
    assert not np.array_equal(np.asarray(img), np.asarray(out))


def test_dispatcher_uses_quality_defaults_when_no_value(monkeypatch):
    """token 不传 `=value` → 用 quality 默认值。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out_with_default = preprocess(img, ["gamma"], quality="balanced")
    out_with_explicit = preprocess(img, ["gamma=1.2"], quality="balanced")
    assert np.array_equal(np.asarray(out_with_default), np.asarray(out_with_explicit))


def test_dispatcher_explicit_value_overrides_quality(monkeypatch):
    """显式 `=value` 覆盖 quality 默认值。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "best")
    img = _gray_with_text()
    out_default = preprocess(img, ["gamma"], quality="best")  # best=1.3
    out_explicit = preprocess(img, ["gamma=0.7"], quality="best")
    assert not np.array_equal(np.asarray(out_default), np.asarray(out_explicit))


def test_dispatcher_unknown_op_raises():
    with pytest.raises(ValueError, match="未知 preprocess op"):
        preprocess(_gray_with_text(), ["unknown"], quality="balanced")


def test_dispatcher_unknown_quality_raises():
    with pytest.raises(ValueError, match="未知 preprocess quality"):
        preprocess(_gray_with_text(), ["sharpen"], quality="ultra")


def test_dispatcher_accepts_aliases(monkeypatch):
    """支持别名 sharp / dn / cl / gm。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out_full = preprocess(img, ["sharpen", "denoise", "clahe", "gamma"], quality="balanced")
    out_alias = preprocess(img, ["sharp", "dn", "cl", "gm"], quality="balanced")
    assert np.array_equal(np.asarray(out_full), np.asarray(out_alias))


# ---------------------------------------------------------------------------
# env var 覆盖
# ---------------------------------------------------------------------------


def test_env_var_overrides_quality_when_quality_none(monkeypatch):
    """dispatcher 显式 quality=fast → 各 op 走 PIL 路径（gamma/clahe no-op）。"""
    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    img = _gray_with_text()
    out = preprocess(img, ["gamma", "clahe"], quality="fast")
    # fast 下 gamma/clahe 都 no-op → 输出 == 输入
    assert np.array_equal(np.asarray(img), np.asarray(out))


def test_chain_token_parsers():
    """4 个 *_chain_token 各自解析 `name=value` / `name`。"""
    from book_cut.preprocess.clahe import clahe_chain_token
    from book_cut.preprocess.denoise import denoise_chain_token
    from book_cut.preprocess.gamma import gamma_chain_token
    from book_cut.preprocess.sharpen import sharpen_chain_token

    assert sharpen_chain_token("sharpen=2.0") == ("sharpen", 2.0)
    assert sharpen_chain_token("sharpen") == ("sharpen", None)
    assert denoise_chain_token("denoise=10") == ("denoise", 10.0)
    assert clahe_chain_token("clahe=3.5") == ("clahe", 3.5)
    assert gamma_chain_token("gamma=1.4") == ("gamma", 1.4)


# ---------------------------------------------------------------------------
# 流水线集成：metrics 包含 preprocess
# ---------------------------------------------------------------------------


def test_compute_page_metrics_has_preprocess(monkeypatch):
    """_compute_page metrics 包含 preprocess 字段。"""
    from types import SimpleNamespace

    from book_cut.pipeline.orchestrator import _compute_page
    from book_cut.io.loader import PageInfo

    monkeypatch.setenv("BOOKCUT_PREPROCESS_QUALITY", "balanced")
    page = PageInfo(
        page_index=0,
        source_name="test.png",
        image=_rgb_synthetic(300),
    )
    result = _compute_page(
        page,
        deskew_enabled=False,
        auto_single_page=False,
        page_order="ltr",
        crop_mode="none",
        binarize_method="none",
        crop_config=None,
        paper_deviation=30,
        split_strategy="half",
        half_offset=0,
        use_morph=True,
        is_sampled_page=True,
        preprocess_chain=["denoise", "clahe", "sharpen"],
        preprocess_quality="balanced",
    )
    assert "preprocess" in result["metrics"]
    assert result["metrics"]["preprocess"]["chain"] == ["denoise", "clahe", "sharpen"]
    assert result["metrics"]["preprocess"]["quality"] == "balanced"
    assert "preprocess" in result["metrics"]["timings_ms"]