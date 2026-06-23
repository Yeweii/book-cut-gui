"""伽马 / 亮度校正（v1.9+）：调整整体明暗。

解决古籍深底封面 / 过曝扫描。公式 ``out = (in / 255) ^ γ * 255``。

约定（标准图像处理）：
- ``γ < 1``：提亮（适合深底封面、暗扫描）
- ``γ = 1``：no-op
- ``γ > 1``：压暗（适合过曝扫描）

三档实现：
- fast：γ=1.0（no-op，等价原图）
- balanced：γ=1.2（轻度提亮；适合深底扫描）
- best：γ=1.3（略强；用户可手动调到任意值）

操作数：
- 输入 ``Image`` / ``ndarray``
- 输出保持原 dtype / mode
- value 限制 ∈ ``[0.25, 4.0]``（out-of-range 抛 ``ValueError``）
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

_GAMMA_MIN = 0.25
_GAMMA_MAX = 4.0


def _get_quality() -> str:
    return os.environ.get("BOOKCUT_PREPROCESS_QUALITY", "balanced").lower()


def _default_gamma(quality: str) -> float:
    return {"fast": 1.0, "balanced": 1.2, "best": 1.3}.get(quality, 1.2)


def _validate_gamma(value: float) -> float:
    """clamp 检查伽马值；out-of-range raise。"""
    if value <= 0:
        raise ValueError(f"gamma value 必须 > 0，收到 {value}")
    if value < _GAMMA_MIN or value > _GAMMA_MAX:
        raise ValueError(
            f"gamma value 必须在 [{_GAMMA_MIN}, {_GAMMA_MAX}] 内，收到 {value}"
        )
    return value


def gamma_from_array(
    arr: np.ndarray,
    value: float = 1.2,
    quality: str | None = None,
) -> np.ndarray:
    """伽马校正核心（v1.9+ A1：接受 ndarray）。

    Args:
        arr: 输入 ndarray（uint8 或 float32；2D 灰度或 3D 彩色）。
        value: 伽马值（>0）；>1 变暗，<1 变亮。古籍常用 1.1~1.4。
        quality: 覆盖 ``BOOKCUT_PREPROCESS_QUALITY``。

    Returns:
        ndarray，dtype 与输入相同。
    """
    q = (quality or _get_quality()).lower()
    if q == "fast":
        # fast 档 no-op（保持 v1.8 行为，零延迟）
        return arr

    _validate_gamma(value)
    # 归一化到 [0, 1] → γ 次幂 → 还原到 [0, 255]
    # γ<1 提亮，γ>1 压暗（标准图像处理约定）
    out = np.power(arr / 255.0, value) * 255.0
    return out.astype(arr.dtype)


def gamma(
    image: Image.Image,
    value: float | None = None,
    quality: str | None = None,
) -> Image.Image:
    """PIL Image wrapper：自动处理 L/RGB 模式。

    Args:
        image: 输入图像（任意模式，会先 ``convert("L")``）。
        value: 伽马值；``None`` → 按 quality 默认。
        quality: fast/balanced/best；``None`` → 读环境变量。
    """
    q = (quality or _get_quality()).lower()
    if value is None:
        value = _default_gamma(q)

    if image.mode != "L":
        image = image.convert("L")
    arr = np.asarray(image, dtype=np.uint8)
    out = gamma_from_array(arr, value=value, quality=q)
    return Image.fromarray(out, mode="L")


def gamma_chain_token(token: str) -> tuple[str, float | None]:
    """解析 ``"gamma"`` 或 ``"gamma=1.3"`` → ``("gamma", value_or_None)``。"""
    token = token.strip()
    if "=" in token:
        name, val = token.split("=", 1)
        return name.strip(), float(val)
    return token, None
