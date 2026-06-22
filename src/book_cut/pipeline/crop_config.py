"""crop_config：CLI args → CropConfig + per-page override 决策。

职责：
- ``_build_crop_config(args, sample_pages)``：构造书级 CropConfig
- ``_resolve_per_page_config(sub_arr, book_config, deviation)``：单页 override 决策

v1.6+ C3：从原 ``pipeline.py`` 拆出，独立模块。
"""

from __future__ import annotations

import numpy as np


def _resolve_per_page_config(
    sub_arr: np.ndarray,
    book_config,
    deviation: float,
) -> object | None:
    """v1.5+ per-page override 决策：单张子图用书级还是 per-page config。

    Args:
        sub_arr: 单张子图灰度 ndarray（已切分后）。
        book_config: 书级 CropConfig（``None`` → 走 legacy，不 override）。
        deviation: 偏离阈值（``--paper-deviation``，默认 30）。

    Returns:
        - ``book_config``：不 override（per-paper 接近 book）
        - 新 ``CropConfig``：override 触发（保持 padding/ink_offset，仅换 paper_color）
        - ``None``：legacy 模式（与 book_config=None 对齐）
    """
    if book_config is None:
        return None  # legacy fixed 模式：不 override
    from book_cut.detect.paper import (
        CropConfig,
        estimate_paper_color_from_array,
        should_override,
    )

    per_paper = estimate_paper_color_from_array(sub_arr)
    if not should_override(per_paper, book_config.paper_color, threshold=deviation):
        return book_config  # 偏离 ≤ 阈值：沿用书级

    # override：保持 padding/ink_offset/min_edge_ink，只换 paper_color
    # v1.5+ §5.1：padding 不变（视觉一致性），仅 ink_thr 切到 per-page
    return CropConfig(
        paper_color=per_paper,
        ink_offset=book_config.ink_offset,
        padding=book_config.padding,
        min_edge_ink=book_config.min_edge_ink,
    )


def _build_crop_config(args, sample_pages: list) -> object | None:
    """根据 CLI args 构造 ``CropConfig``（或返 ``None`` 走 legacy 路径）。

    行为表：
    - ``--crop-adaptive fixed`` → 返 ``None``（legacy 阈值 240）
    - ``--crop-adaptive auto`` 且 ``--paper-pages >= 1`` → 用前 N 页估 book paper color
    - ``--crop-adaptive auto`` 且 ``--paper-pages 0/1`` → 每页单独估（每次都算）
    """
    from book_cut.detect.paper import (
        aggregate_paper_color,
        default_crop_config,
        estimate_paper_color,
    )

    crop_adaptive: str = getattr(args, "crop_adaptive", "auto")
    if crop_adaptive == "fixed":
        return None  # legacy 模式：trim/border 走硬编码 threshold=240

    paper_pages: int = max(0, getattr(args, "paper_pages", 5))
    if not sample_pages or paper_pages == 0:
        # 无样页可用：返一个默认 config，每页用 240 (等同 legacy)
        return default_crop_config(paper_color=240.0)

    sampled = sample_pages[:paper_pages]
    colors = [estimate_paper_color(p.image) for p in sampled]
    book_paper = aggregate_paper_color(colors)
    print(
        f"[INFO] 自适应裁切: book paper color = {book_paper:.1f} "
        f"(sampled {len(colors)} pages, raw = {[round(c, 1) for c in colors]})"
    )
    return default_crop_config(paper_color=book_paper)