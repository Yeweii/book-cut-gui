"""CLI 端到端测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 让 subprocess 能找到 book_cut 模块
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_ENV = {**os.environ, "PYTHONPATH": str(_SRC)}


def test_cli_help():
    """``--help`` 能跑通。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    assert "古籍双页切分" in result.stdout


def test_cli_no_morph_flag_accepted():
    """v1.6+ ``--no-morph`` flag 能被 argparse 接受。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--no-morph" in result.stdout


def test_cli_split_half_help_warns_centering():
    """v1.6+ ``--split half`` help 文字有"严格居中"警告。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "严格居中" in result.stdout or "居中" in result.stdout


def test_cli_paper_deviation_flag_accepted():
    """v1.5+ ``--paper-deviation`` flag 存在。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--paper-deviation" in result.stdout


def test_cli_trim_source_flag_accepted():
    """v2.1+ ``--trim-source`` flag 存在（trim A 方案）。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-source" in result.stdout


def test_cli_trim_min_component_ratio_flag_accepted():
    """v2.1+ ``--trim-min-component-ratio`` flag 存在（trim B 方案）。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-min-component-ratio" in result.stdout


def test_cli_trim_padding_flag_accepted():
    """v2.1+ ``--trim-padding`` flag 存在（trim C 方案）。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-padding" in result.stdout


def test_cli_trim_gutter_band_flag_accepted():
    """v2.1+ ``--trim-gutter-band`` flag 存在（trim D 方案）。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--trim-gutter-band" in result.stdout


def test_cli_adaptive_padding_flag_accepted():
    """v2.1+ ``--adaptive-padding`` flag 存在（adaptive padding 覆盖）。"""
    result = subprocess.run(
        [sys.executable, "-m", "book_cut.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env=_ENV,
    )
    assert "--adaptive-padding" in result.stdout


def test_cli_runs_no_morph(tmp_path):
    """v1.6+ ``--no-morph`` 端到端跑通：合成 PDF → --no-morph → 不报错。"""
    from io import BytesIO

    import numpy as np
    import pymupdf
    from PIL import Image

    # 合成 3 页 PDF：每页有 1-2 个 1px 孤立尘点（≤ min_ink=3 不触发 trim）
    png_bytes = []
    for _ in range(3):
        arr = np.full((300, 400), 255, dtype=np.uint8)
        # 内容 5×5 实心块（保字）
        arr[100:105, 150:155] = 30
        # 几个 1px 尘点（≤ min_ink 不影响 trim）
        arr[10, 10] = 0
        img = Image.fromarray(arr, mode="L")
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes.append(buf.getvalue())

    doc = pymupdf.open()
    for png in png_bytes:
        page = doc.new_page(width=400, height=300)
        page.insert_image(page.rect, stream=png)
    in_pdf = tmp_path / "input.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"

    # 跑 CLI with --no-morph
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "book_cut.cli",
            "--input",
            str(in_pdf),
            "--output",
            str(out_dir),
            "--split",
            "half",
            "--crop",
            "trim",
            "--binarize",
            "none",
            "--no-morph",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=_ENV,
    )
    assert result.returncode == 0, f"CLI 失败: stderr={result.stderr}"
    out_files = sorted(out_dir.glob("*.png"))
    # 3 页 × 2 (half 切) = 6 张
    assert len(out_files) == 6
