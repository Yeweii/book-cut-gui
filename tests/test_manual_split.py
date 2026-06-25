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
