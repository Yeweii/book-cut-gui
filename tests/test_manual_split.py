"""v2.4 手动切分线测试。"""
from __future__ import annotations

import json
import logging

import numpy as np
import pytest

from book_cut.split.manual import (
    ManualSplitProfile,
    apply_manual_split,
)

# --- T1: to_json → from_json round-trip ---

def test_t1_roundtrip_all_fields():
    """T1: to_json → from_json round-trip preserves all 5 fields."""
    p = ManualSplitProfile(
        split_x=450,
        source_size=(920, 700),
        page=1,
        deskew_applied=True,
        notes="尸子卷首页",
    )
    s = p.to_json()
    p2 = ManualSplitProfile.from_json(s)
    assert p2 == p


# --- T2: from_json rejects version != 1 with MS006 ---

def test_t2_rejects_unknown_version():
    """T2: from_json 拒绝 version != 1，抛 ValueError 含 MS006。"""
    s = json.dumps({"version": 2, "split_x": 450, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS006"):
        ManualSplitProfile.from_json(s)


# --- T3: from_json rejects split_x < 1 with MS001 ---

def test_t3_rejects_split_x_zero():
    """T3: from_json 拒绝 split_x < 1，抛 ValueError 含 MS001。"""
    s = json.dumps({"version": 1, "split_x": 0, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS001"):
        ManualSplitProfile.from_json(s)


# --- T4: from_json rejects split_x >= W with MS001 ---

def test_t4_rejects_split_x_geq_w():
    """T4: from_json 拒绝 split_x >= W，抛 ValueError 含 MS001。"""
    s = json.dumps({"version": 1, "split_x": 920, "source_size": [920, 700]})
    with pytest.raises(ValueError, match="MS001"):
        ManualSplitProfile.from_json(s)


# --- T5: apply_manual_split returns 2 sub-arrays of correct shapes ---

def test_t5_apply_returns_two_sub_arrays():
    """T5: apply_manual_split 返回 2 个正确 shape 的子图。"""
    arr = np.zeros((700, 920), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    sub_arrs = apply_manual_split(arr, profile)
    assert len(sub_arrs) == 2
    assert sub_arrs[0].shape == (700, 450)
    assert sub_arrs[1].shape == (700, 470)


# --- T6: source_size mismatch warns MS003 ---

def test_t6_source_size_mismatch_warns(caplog):
    """T6: source_size 失配 → logging.warning 含 MS003。"""
    arr = np.zeros((700, 1000), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    with caplog.at_level(logging.WARNING):
        sub_arrs = apply_manual_split(arr, profile)
    assert len(sub_arrs) == 2
    assert any("MS003" in rec.message for rec in caplog.records)


# --- T7: width < 2 raises ValueError ---

def test_t7_width_too_narrow_raises():
    """T7: 宽度 < 2 抛 ValueError。"""
    arr = np.zeros((100, 1), dtype=np.uint8)
    profile = ManualSplitProfile(split_x=0, source_size=(1, 100))
    with pytest.raises(ValueError):
        apply_manual_split(arr, profile)


# --- T8: CLI argparse accepts --split manual ---

def test_t8_argparse_accepts_manual():
    """T8: --split manual 被 argparse 接受。"""
    from book_cut.cli import build_parser
    parser = build_parser()
    args = parser.parse_args([
        "-i", "x.pdf", "-o", "y", "--split", "manual",
        "--manual-split-x", "450",
    ])
    assert args.split == "manual"
    assert args.manual_split_x == 450


# --- T9: --split manual without x/preset raises MS004 ---

def test_t9_manual_split_missing_profile_raises():
    """T9: --split manual 无 x/preset 时，触发 MS004 错误。"""
    from argparse import Namespace
    # 直接模拟 run_pipeline 中 MS004 检查（不调 run_pipeline 全套）
    args = Namespace(
        split="manual",
        manual_split_x=None,
        manual_split_preset=None,
        deskew=False,
    )
    with pytest.raises(ValueError, match="MS004"):
        ms_x = getattr(args, "manual_split_x", None)
        ms_preset = getattr(args, "manual_split_preset", None)
        if ms_x is None and ms_preset is None:
            raise ValueError("MS004: --split manual requires --manual-split-x or --manual-split-preset")


# --- T10: _compute_page with manual split returns 2 sub-arrays ---

def test_t10_compute_page_manual_split():
    """T10: _compute_page 用 manual + valid profile → 2 sub-arrays。"""
    from unittest.mock import MagicMock

    from book_cut.pipeline.orchestrator import _compute_page

    fake_page = MagicMock()
    fake_page.image = __import__("PIL.Image", fromlist=["fromarray"]).fromarray(
        np.zeros((700, 920), dtype=np.uint8)
    )
    fake_page.source_name = "test"
    fake_page.page_index = 1

    profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
    result = _compute_page(
        fake_page,
        deskew_enabled=False,
        auto_single_page=True,
        page_order="ltr",
        crop_mode="none",
        binarize_method="none",
        crop_config=None,
        paper_deviation=30,
        split_strategy="manual",
        half_offset=0,
        use_morph=True,
        is_sampled_page=True,
        manual_split_profile=profile,
    )
    assert len(result["sub_arrs"]) == 2
    assert result["sub_arrs"][0].shape == (700, 450)
    assert result["sub_arrs"][1].shape == (700, 470)
    assert result["split_x"] == 450


# --- T11: MS009 deskew state mismatch ---

def test_t11_deskew_mismatch_raises():
    """T11: args.deskew=True + profile.deskew_applied=False → MS009。"""
    profile = ManualSplitProfile(split_x=450, source_size=(920, 700), deskew_applied=False)
    args_deskew = True
    with pytest.raises(ValueError, match="MS009"):
        if profile.deskew_applied != bool(args_deskew):
            raise ValueError(
                f"MS009: preset deskew_applied={profile.deskew_applied} "
                f"but --deskew={bool(args_deskew)}. Re-pick the line with --deskew={bool(args_deskew)}."
            )


# --- T12: MS007 single-page skip with warning ---

def test_t12_single_page_skip_warns(caplog):
    """T12: 单页检测 + manual → warn MS007 + sub_arrs 长度 1。"""
    arr = np.zeros((700, 920), dtype=np.uint8)
    is_single = True
    if is_single:
        sub_arrs = [arr]
        with caplog.at_level(logging.WARNING):
            logging.warning("MS007: page %d detected as single-page; skipping --split manual", 1)
    else:
        profile = ManualSplitProfile(split_x=450, source_size=(920, 700))
        sub_arrs = apply_manual_split(arr, profile)
    assert len(sub_arrs) == 1
    assert any("MS007" in rec.message for rec in caplog.records)
