"""处理流水线：orchestrator + outline + crop_config 三模块组合。

v1.6+ C3：从单文件 455 行 ``pipeline.py`` 拆出 3 模块：
- ``orchestrator``：流水线主循环（``run_pipeline`` 公共入口）
- ``outline``：PDF outline / metadata 来源解析与合并 PDF 写出
- ``crop_config``：CLI args → CropConfig + per-page override 决策

公共 API 不变：
- ``from book_cut.pipeline import run_pipeline``（主入口）
- ``from book_cut.pipeline import _first_and_count_pdfs`` / ``_resolve_outline_source``
  （被 ``tests/test_a4_a5_perf.py`` 引用，向后兼容 re-export）
"""

from __future__ import annotations

from book_cut.pipeline.orchestrator import run_pipeline
from book_cut.pipeline.outline import _first_and_count_pdfs, _resolve_outline_source

__all__ = [
    "run_pipeline",
    "_first_and_count_pdfs",
    "_resolve_outline_source",
]
