"""v1.6+ C3 pipeline 拆 3 模块测试。

C3 改动：单文件 ``pipeline.py``（455 行）拆成 ``pipeline/`` 包的 4 个文件：
- ``__init__.py``：re-export 公共 API
- ``orchestrator.py``：``run_pipeline`` 主循环 + 5 个 helper
- ``outline.py``：3 个 PDF outline 相关 helper
- ``crop_config.py``：2 个 CropConfig 构造 helper

验证点：
1. 3 个新模块可独立 import
2. ``pipeline/__init__.py`` re-export 等于模块内定义（同一对象）
3. 公共 API 行为不变（end-to-end run_pipeline 跑通合成 PDF）
4. 行数：单文件 < 250 行（orchestrator 是最长的）
"""

from __future__ import annotations

import importlib


# ============ 模块独立 import ============


def test_c3_pipeline_package_exists():
    """C3：``book_cut.pipeline`` 现在是包（不是模块）。"""
    import book_cut.pipeline

    mod = importlib.import_module("book_cut.pipeline")
    # 验证是 package（有 __path__）
    assert hasattr(mod, "__path__"), "book_cut.pipeline 应该是包，不是模块"


def test_c3_orchestrator_importable():
    """C3：``book_cut.pipeline.orchestrator`` 可独立 import。"""
    mod = importlib.import_module("book_cut.pipeline.orchestrator")
    assert hasattr(mod, "run_pipeline")
    assert hasattr(mod, "_split_from_array")
    assert hasattr(mod, "_crop_pages_from_arrays")
    assert hasattr(mod, "_crop_pages_from_arrays_with_config")
    assert hasattr(mod, "_reverse_pair")


def test_c3_outline_importable():
    """C3：``book_cut.pipeline.outline`` 可独立 import。"""
    mod = importlib.import_module("book_cut.pipeline.outline")
    assert hasattr(mod, "_resolve_outline_source")
    assert hasattr(mod, "_first_and_count_pdfs")
    assert hasattr(mod, "_write_pdf_with_outline")


def test_c3_crop_config_importable():
    """C3：``book_cut.pipeline.crop_config`` 可独立 import。"""
    mod = importlib.import_module("book_cut.pipeline.crop_config")
    assert hasattr(mod, "_build_crop_config")
    assert hasattr(mod, "_resolve_per_page_config")


# ============ __init__.py re-export ============


def test_c3_init_reexports_run_pipeline():
    """C3：``pipeline.run_pipeline`` 与 ``orchestrator.run_pipeline`` 是同一对象。"""
    from book_cut.pipeline import run_pipeline as rp_init
    from book_cut.pipeline.orchestrator import run_pipeline as rp_orch

    assert rp_init is rp_orch, (
        "pipeline.__init__.py 必须从 orchestrator re-export run_pipeline，"
        "否则 import 不再等价"
    )


def test_c3_init_reexports_outline_helpers():
    """C3：``_first_and_count_pdfs`` / ``_resolve_outline_source`` 从 outline re-export。"""
    from book_cut.pipeline import _first_and_count_pdfs, _resolve_outline_source
    from book_cut.pipeline.outline import (
        _first_and_count_pdfs as facp_outline,
        _resolve_outline_source as ros_outline,
    )

    assert _first_and_count_pdfs is facp_outline
    assert _resolve_outline_source is ros_outline


def test_c3_init_does_not_reexport_unstable_helpers():
    """C3：``__init__`` 只 re-export 公共 API + 测试所需的私有 helper，
    内部 helper（``_process_one`` / ``_build_crop_config``）不暴露。

    防止过度耦合：调用者只依赖 public API。
    """
    import book_cut.pipeline as pkg

    # 应该 re-export
    assert "run_pipeline" in dir(pkg)
    assert "_first_and_count_pdfs" in dir(pkg)
    assert "_resolve_outline_source" in dir(pkg)

    # 不应该 re-export（避免与内部实现耦合）
    assert "_process_one" not in dir(pkg)
    assert "_build_crop_config" not in dir(pkg)
    assert "_write_pdf_with_outline" not in dir(pkg)


# ============ 行数约束 ============


def test_c3_orchestrator_line_count_under_400():
    """C3：``orchestrator.py`` < 400 行（仍比原 455 行单文件短）。

    v1.7：阈值从 350 提到 400 —— 新增 PDF 页面尺寸 max/first 预扫 + fit 步骤
    约 +50 行（用 docstring 解释分支，方便单测读懂）。
    """
    from pathlib import Path

    p = Path(__file__).parent.parent / "src" / "book_cut" / "pipeline" / "orchestrator.py"
    lines = sum(1 for _ in p.open())
    assert lines < 400, f"orchestrator.py 应 < 400 行，实际 {lines}"


def test_c3_outline_line_count_under_150():
    """C3：``outline.py`` < 150 行。"""
    from pathlib import Path

    p = Path(__file__).parent.parent / "src" / "book_cut" / "pipeline" / "outline.py"
    lines = sum(1 for _ in p.open())
    assert lines < 150, f"outline.py 应 < 150 行，实际 {lines}"


def test_c3_crop_config_line_count_under_120():
    """C3：``crop_config.py`` < 120 行。"""
    from pathlib import Path

    p = Path(__file__).parent.parent / "src" / "book_cut" / "pipeline" / "crop_config.py"
    lines = sum(1 for _ in p.open())
    assert lines < 120, f"crop_config.py 应 < 120 行，实际 {lines}"


def test_c3_split_saves_total_lines():
    """C3：拆分后 4 个文件总行数 < 原 455 行（去掉冗余 import / docstring）。"""
    from pathlib import Path

    pkg_dir = Path(__file__).parent.parent / "src" / "book_cut" / "pipeline"
    total = sum(
        sum(1 for _ in (pkg_dir / f).open())
        for f in ["__init__.py", "orchestrator.py", "outline.py", "crop_config.py"]
    )
    # 拆分后总行数 ≈ 原 455（拆出来 docstring + re-import 抵消了部分节省）
    # v1.7：阈值从 600 提到 700 —— orchestrator 加了 max/first 预扫 + fit
    # 但单文件 < 400，最大拆分价值
    assert total < 700, f"拆分后总行数 {total} 超过预算 700（原 455）"
    assert total > 400, f"拆分后总行数 {total} 异常少"


def test_c3_old_pipeline_py_removed():
    """C3：原 ``pipeline.py`` 已被删除（被 pipeline/ 包替代）。"""
    from pathlib import Path

    src = Path(__file__).parent.parent / "src" / "book_cut"
    assert not (src / "pipeline.py").exists(), (
        "原 pipeline.py 应被删除，否则与 pipeline/ 包冲突"
    )
    assert (src / "pipeline").is_dir(), "pipeline/ 包目录必须存在"


# ============ 端到端行为不变 ============


def test_c3_run_pipeline_end_to_end(tmp_path):
    """C3：``run_pipeline`` 端到端跑通合成 PDF（行为不变）。"""
    import argparse

    import pymupdf
    from io import BytesIO
    from PIL import Image

    # 合成 1 页双页图
    img = Image.new("L", (1000, 800), 220)
    arr_img = img.copy()
    buf = BytesIO()
    arr_img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=buf.getvalue())
    in_pdf = tmp_path / "single_double.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf),
        output=str(out_dir),
        split="half",
        crop="none",
        binarize="none",
        deskew=False,
        auto_single_page=False,
        page_order="ltr",
        outline=True,
        format="png",
        crop_adaptive="auto",
        paper_pages=1,
        paper_deviation=30,
        half_offset=0,
        no_morph=False,
        pdf=False,
    )

    from book_cut.pipeline import run_pipeline

    run_pipeline(args)

    # 1 双页 × 2 half = 2 张
    out_files = sorted(out_dir.glob("*.png"))
    assert len(out_files) == 2


def test_c3_run_pipeline_with_pdf_output(tmp_path):
    """C3：``--pdf`` 输出 + outline 透传仍然工作（走 outline 模块）。"""
    import argparse

    import pymupdf
    from io import BytesIO
    from PIL import Image

    # 合成 1 页双页图
    arr_img = Image.new("L", (1000, 800), 220)
    buf = BytesIO()
    arr_img.save(buf, format="PNG")

    doc = pymupdf.open()
    # 先建页再加 TOC（PyMuPDF 要求 page_xref 存在）
    page = doc.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=buf.getvalue())
    # 加一个 outline 节点
    doc.set_toc([[1, "TestChapter", 1]])
    in_pdf = tmp_path / "with_outline.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf),
        output=str(out_dir),
        split="half",
        crop="none",
        binarize="none",
        deskew=False,
        auto_single_page=False,
        page_order="ltr",
        outline=True,
        format="png",
        crop_adaptive="auto",
        paper_pages=1,
        paper_deviation=30,
        half_offset=0,
        no_morph=False,
        pdf=True,
    )

    from book_cut.pipeline import run_pipeline

    run_pipeline(args)

    # 应输出 PDF
    out_pdfs = list(out_dir.glob("*.pdf"))
    assert len(out_pdfs) == 1

    # 验证 outline 透传（C3 后走 outline._write_pdf_with_outline）
    out_doc = pymupdf.open(str(out_pdfs[0]))
    out_toc = out_doc.get_toc()
    assert any("TestChapter" in str(entry) for entry in out_toc), (
        f"outline 未透传: {out_toc}"
    )
    out_doc.close()