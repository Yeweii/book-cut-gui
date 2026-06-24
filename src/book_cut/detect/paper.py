"""纸张色（paper color）估计与裁切配置。

提供：
- ``CropConfig``：自适应裁切参数集合（paper_color、ink_offset、padding、min_edge_ink）
- ``estimate_paper_color``：单页 paper color 估计（95th percentile，clip [180, 255]）
- ``aggregate_paper_color``：多页 → 书级 paper color（median）
- ``adaptive_padding``：按图像尺寸比例算 padding
- ``default_crop_config``：工厂函数

设计要点：
- **95th percentile** 比 median 抗浓墨（cover 50% 浓墨仍返 255）；比 Otsu 简单。
- **median 聚合** 抗单页异常（一页 cover 不会拉低书级）。
- **CropConfig frozen=True** 保证 hashable，方便测试与将来缓存。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class CropConfig:
    """自适应裁切参数。

    Attributes:
        paper_color: 估计的纸色灰度，∈ [180, 255]。
        ink_offset: ink 阈值偏移；``ink_threshold = max(paper_color - ink_offset, 60)``。
        padding: 裁切后保留的最小边距。``None`` → 调用方按 ``adaptive_padding(h, w)`` 计算。
        min_edge_ink: 判定行/列"有内容"所需的最小 ink 像素数；抗单像素噪声。
    """

    paper_color: float = 240.0
    ink_offset: float = 30.0
    padding: int | None = None
    min_edge_ink: int = 3

    @property
    def ink_threshold(self) -> float:
        """ink 阈值：纸色 − 偏移，下限 60（防泛黑页面塌缩）。"""
        return max(self.paper_color - self.ink_offset, 60.0)


def estimate_paper_color(image: Image.Image) -> float:
    """估计单张图像的 paper color（0-255 灰度）。

    策略：取灰度直方图的 95th percentile，clip 到 [180, 255]。
    - 抗 50% 浓墨（cover 仍返 ~255，因为最亮 5% 像素还是白纸）
    - 抗单像素噪声（per-image 全局聚合）
    - 比 Otsu 简单（Otsu 给的是阈值，要再反推 paper color）

    Args:
        image: PIL 图像（任意 mode；非 L 模式会自动转灰度）。

    Returns:
        paper color ∈ [180, 255]。空图返 255.0。
    """
    if image.mode != "L":
        gray = image.convert("L")
    else:
        gray = image
    arr = np.asarray(gray)
    if arr.size == 0:
        return 255.0
    p95 = float(np.percentile(arr, 95))
    # 真实古籍 paper 范围：180 (重度黄化/灰化) ~ 255 (漂白)。
    # 超出此范围几乎肯定是墨迹或阴影，不是纸色。
    return max(180.0, min(255.0, p95))


def aggregate_paper_color(colors: list[float]) -> float:
    """聚合多页 paper color 为书级估计。

    策略：median（鲁棒于 ≤ 50% 异常页，如 cover/插页）。
    - 空列表 → 255.0（兜底）
    - 单元素 → 原值

    Args:
        colors: 各页 paper color。

    Returns:
        书级 paper color。
    """
    if not colors:
        return 255.0
    if len(colors) == 1:
        return float(colors[0])
    return float(np.median(colors))


def adaptive_padding(h: int, w: int) -> int:
    """按图像尺寸算自适应 padding。

    公式：``max(int(min(h, w) * 0.02), 5)``，clamp 到 ≤ 30。
    - 700px 短边 → 14px
    - 1500px → 30px (cap)
    - 4000px → 30px (cap)
    - 小于 250px → 5px (floor)

    Args:
        h: 图像高。
        w: 图像宽。

    Returns:
        像素 padding。
    """
    base = int(min(h, w) * 0.02)
    return max(5, min(30, base))


def default_crop_config(paper_color: float | None = None) -> CropConfig:
    """工厂函数：构造一个 CropConfig。

    Args:
        paper_color: 纸色。``None`` → 240（v1.1 兼容值）。

    Returns:
        新 ``CropConfig`` 实例。
    """
    if paper_color is None:
        paper_color = 240.0
    return CropConfig(paper_color=paper_color)
