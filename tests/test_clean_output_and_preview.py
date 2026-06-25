"""v2.3.5+ --clean-output + dry-run 旧预览自动清理测试。

覆盖：
- cleanup_old_previews：扫描 tmpdir，删 >max_age_days 的 book-cut-preview-*
- cleanup_old_previews：保留 <max_age_days 的新目录
- cleanup_old_previews：不动非 book-cut-preview-* 目录
- cleanup_old_previews：max_age_days=0 → 全部清掉
- cleanup_old_previews：tmpdir 不存在 → 返回 0
- --clean-output argparse：默认 False；--clean-output=True；--no-clean-output=False
- orchestrator：--clean-output=True + dry-run=True → **不删**（dry-run 不动 output_dir）
"""

from __future__ import annotations

import os
import time
from argparse import Namespace
from pathlib import Path

from book_cut.cli import build_parser
from book_cut.pipeline.dry_run import (
    _PREVIEW_DIR_PREFIX,
    DEFAULT_PREVIEW_MAX_AGE_DAYS,
    cleanup_old_previews,
)

# ----------------------------------------------------------------------------
# T1-T5：cleanup_old_previews
# ----------------------------------------------------------------------------


def _make_preview_dir(parent: Path, name: str, age_days: float) -> Path:
    """在 parent 下建一个 book-cut-preview-* 目录，mtime 设为 age_days 天前。"""
    d = parent / f"{_PREVIEW_DIR_PREFIX}{name}"
    d.mkdir()
    (d / "f.txt").write_text("x")
    age_sec = age_days * 86400
    target_mtime = time.time() - age_sec
    os.utime(d, (target_mtime, target_mtime))
    return d


def test_t1_removes_old_previews(tmp_path: Path) -> None:
    """T1：30 天前的 book-cut-preview-* 目录应被删。"""
    old = _make_preview_dir(tmp_path, "1000000", age_days=30)
    n = cleanup_old_previews(max_age_days=7, tmpdir=tmp_path)
    assert n == 1
    assert not old.exists()


def test_t2_keeps_fresh_previews(tmp_path: Path) -> None:
    """T2：1 天前的目录 < 7 天阈值，保留。"""
    fresh = _make_preview_dir(tmp_path, "9999", age_days=1)
    n = cleanup_old_previews(max_age_days=7, tmpdir=tmp_path)
    assert n == 0
    assert fresh.exists()


def test_t3_ignores_non_preview_dirs(tmp_path: Path) -> None:
    """T3：非 book-cut-preview-* 前缀的目录（即使超期）不动。"""
    other = tmp_path / "my-old-data-30d"
    other.mkdir()
    (other / "x.txt").write_text("y")
    os.utime(other, (time.time() - 30 * 86400, time.time() - 30 * 86400))
    n = cleanup_old_previews(max_age_days=7, tmpdir=tmp_path)
    assert n == 0
    assert other.exists()


def test_t4_max_age_zero_removes_all(tmp_path: Path) -> None:
    """T4：max_age_days=0 → 所有 prefix 目录都清（边界：mtime == now 时 (now-mtime) > 0 成立）。"""
    a = _make_preview_dir(tmp_path, "1", age_days=0)
    b = _make_preview_dir(tmp_path, "2", age_days=0)
    n = cleanup_old_previews(max_age_days=0, tmpdir=tmp_path)
    assert n == 2
    assert not a.exists()
    assert not b.exists()


def test_t5_missing_tmpdir_returns_zero(tmp_path: Path) -> None:
    """T5：tmpdir 不存在 → 返回 0，不抛。"""
    n = cleanup_old_previews(max_age_days=7, tmpdir=tmp_path / "nonexistent")
    assert n == 0


def test_t6_default_max_age_is_7_days() -> None:
    """T6：DEFAULT_PREVIEW_MAX_AGE_DAYS = 7。"""
    assert DEFAULT_PREVIEW_MAX_AGE_DAYS == 7


def test_t7_uses_default_tmpdir_when_none() -> None:
    """T7：tmpdir=None 时用 tempfile.gettempdir()，不会崩。

    实际是否删东西取决于系统状态；这里只验证签名 + 不抛。
    """
    n = cleanup_old_previews(max_age_days=99999)
    assert isinstance(n, int)


# ----------------------------------------------------------------------------
# T8-T10：--clean-output argparse
# ----------------------------------------------------------------------------


def test_t8_clean_output_default_false() -> None:
    """T8：--clean-output 默认 False（保护用户数据）。"""
    args = build_parser().parse_args(["-i", "/tmp/in", "-o", "/tmp/out"])
    assert args.clean_output is False


def test_t9_clean_output_flag_true() -> None:
    """T9：--clean-output → True。"""
    args = build_parser().parse_args(["-i", "/tmp/in", "-o", "/tmp/out", "--clean-output"])
    assert args.clean_output is True


def test_t10_no_clean_output_flag_false() -> None:
    """T10：--no-clean-output → False（BooleanOptionalAction 显式否定）。"""
    args = build_parser().parse_args(["-i", "/tmp/in", "-o", "/tmp/out", "--no-clean-output"])
    assert args.clean_output is False


# ----------------------------------------------------------------------------
# T11-T12：orchestrator 集成（dry-run 不删 / 非 dry-run + clean_output 删）
# ----------------------------------------------------------------------------


def _build_args(
    *,
    output: Path,
    clean_output: bool = False,
    dry_run: bool = False,
) -> Namespace:
    """构造一个最小可用的 Namespace。"""
    return Namespace(
        input="/nonexistent",
        output=str(output),
        clean_output=clean_output,
        dry_run=dry_run,
        sample_n=1,
        preview_output=None,
        binarize="none",
        binary_mode="8bit",
        binarize_cleanup="components",
        split="gutter",
        half_offset=0,
        deskew=False,
        auto_single_page=True,
        crop="none",
        crop_config=None,
        paper_deviation=30.0,
        use_morph=True,
        preprocess="",
        preprocess_quality="balanced",
        trim_source="gray",
        min_component_ratio=0.0,
        extra_padding=0,
        gutter_band=None,
        gutter_bands=None,
        horizontal=True,
        trim_strict=False,
        trim_frame=False,
        trim_frame_min_ratio=0.30,
        trim_frame_max_fill=0.15,
        page_order="ltr",
        outline=True,
        no_morph=False,
        no_outline=False,
        format="png",
        pdf=False,
        pdf_page_size="keep",
        pdf_page_dim="0x0",
        pdf_page_unit="mm",
        manual_odd_padding=None,
        manual_even_padding=None,
        manual_mirror_even=False,
        manual_preset=None,
        max_pages=999,
    )


def test_t11_dry_run_does_not_clean_output(tmp_path: Path) -> None:
    """T11：dry-run + clean_output=True → **不删**（dry-run 承诺不动 output_dir）。"""
    import shutil

    in_dir = tmp_path / "in"
    in_dir.mkdir()
    shutil.copy(
        "/Users/yewei/codes/vibe codes/book-cut/samples/尸子卷上下.浙江书局.光绪三年刊_0021.png",
        in_dir / "p.png",
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("important")

    args = _build_args(output=out, clean_output=True, dry_run=True)
    args.input = str(in_dir)
    args.split = "none"

    import threading

    from book_cut.pipeline.orchestrator import run_pipeline

    run_pipeline(args, cancel_event=threading.Event())

    assert (out / "keep.txt").exists(), "dry-run 不应删 output_dir"


def test_t12_clean_output_true_empties_dir(tmp_path: Path) -> None:
    """T12：clean_output=True + 非 dry-run → output_dir 提前 rmtree。

    用一个 fake input 走真实 pipeline（单 PNG 跑通），验证 keep.txt 没了。
    """
    import shutil

    in_dir = tmp_path / "in"
    in_dir.mkdir()
    shutil.copy(
        "/Users/yewei/codes/vibe codes/book-cut/samples/尸子卷上下.浙江书局.光绪三年刊_0021.png",
        in_dir / "p.png",
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "should_be_gone.txt").write_text("x")

    args = _build_args(output=out, clean_output=True, dry_run=False)
    args.input = str(in_dir)
    args.split = "none"  # 单页图直接走 split=none

    import threading

    from book_cut.pipeline.orchestrator import run_pipeline

    run_pipeline(args, cancel_event=threading.Event())

    assert not (out / "should_be_gone.txt").exists(), "--clean-output 应清空旧文件"
    assert (out / "in_0001.png").exists(), "新输出应存在"
