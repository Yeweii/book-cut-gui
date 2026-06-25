"""二值化：Otsu / Adaptive / Sauvola（默认）。

v2.0+：加 ``binary_mode`` 选项，默认 ``"1bit"`` 返回 1-bit 调色板图像
（值 0/1），PNG/PDF 自动走 1-bit 编码，体积缩到 8-bit 输出的 1/8。
"""

from __future__ import annotations

import os
import platform
from typing import Literal

import cv2
import numpy as np
from PIL import Image

BinaryMode = Literal["1bit", "8bit"]

# v1.5+ A2：Sauvola 局部均方的后端选择
# OpenCV 在 arm64 NEON 上对 boxFilter 优化更好（multiply + filter 两次 SIMD pass），
# sqrBoxFilter 在 x86_64 AVX 上更快（fused squaring 一次 pass）。
# 实测（macOS arm64，2026-06-21）：4000×4000 Sauvola
#   boxFilter(arr*arr)  : 61.7-61.8ms ✓
#   sqrBoxFilter(arr)   : 78.8-110.0ms ✗
# 平台默认 + 环境变量 ``BOOKCUT_BINARIZE`` 覆盖（值：``sqrbox`` / ``box``）。
_X86_ARCHES = frozenset({"x86_64", "AMD64", "i386", "i686", "x86"})
_DEFAULT_USE_SQRBOX = platform.machine() in _X86_ARCHES
_USE_SQRBOX = (
    os.environ.get("BOOKCUT_BINARIZE", "sqrbox" if _DEFAULT_USE_SQRBOX else "box").lower()
    == "sqrbox"
)


def _local_mean_sq(arr: np.ndarray, ksize: tuple[int, int]) -> np.ndarray:
    """局部均方（v1.5+ A2 后端选择）。

    x86_64 → ``cv2.sqrBoxFilter``（fused，无临时数组）
    arm64/其他 → ``cv2.boxFilter(arr * arr)``（multiply 后 filter，NEON 优化更佳）

    可用 ``BOOKCUT_BINARIZE=sqrbox|box`` 覆盖默认。
    """
    if _USE_SQRBOX:
        return cv2.sqrBoxFilter(arr, -1, ksize)
    return cv2.boxFilter(arr * arr, -1, ksize)


def _to_gray_array(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.float32)


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    return Image.fromarray(arr_u8, mode="L")


def _to_1bit_image(arr_u8: np.ndarray) -> Image.Image:
    """v2.0+：1-bit 调色板（值 0/1），PNG/PDF 体积缩到 1/8。

    走 ``L → 1`` 路径而非 ``Image.fromarray(bool_arr, mode="1")``：
    后者 PIL 不会直接接受 bool 数组（实测返回全黑），必须先转 L 再 convert。
    ``dither=Image.Dither.NONE`` 避免 Floyd-Steinberg 抖动（binarize 已是硬阈值，
    再 dither 会引入伪影）。
    """
    return Image.fromarray(arr_u8, mode="L").convert("1", dither=Image.Dither.NONE)


# ----------------------------------------------------------------------------
# v2.3.3+：二值化后清理（古籍扫描件去除尘点 / 飞墨噪点）
# ----------------------------------------------------------------------------

#: ``--binarize-cleanup`` argparse choices
BINARIZE_CLEANUP_CHOICES: tuple[str, ...] = ("none", "morph", "components", "both")


def _morph_open(arr_u8: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """形态学开运算（针对黑 specks）：去孤立小 specks。

    OpenCV 的 ``MORPH_OPEN`` 处理的是**前景**（白=255）。我们约定
    黑=0（墨）=前景，白=255（纸）=背景，所以要先 invert → open → invert。

    ``kernel_size=3``（3×3）能完全消除 1-2 px 黑簇，保留 ≥ 3×3 的笔画块。
    对古籍 300 DPI 扫描件：横/竖笔画 3-10 px 宽，损失 1px 可忽略；
    极细末梢（撇、捺、点）会变细但仍可识别。

    注：也可以用 ``MORPH_CLOSE`` 直接填小黑洞，但 CLOSE 是先 dilate 再 erode，
    对笔画边缘的"凸起"不友好；OPEN+invert 更稳。
    """
    if kernel_size < 2:
        return arr_u8
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (kernel_size, kernel_size)
    )
    inv = cv2.bitwise_not(arr_u8)  # 黑→白, 白→黑
    opened = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)  # 去小白色前景
    return cv2.bitwise_not(opened)  # 反转回来


def _drop_small_components(arr_u8: np.ndarray, min_size: int = 4) -> np.ndarray:
    """丢连通域面积 < ``min_size`` 的黑色像素簇（v2.3.3+）。

    算法：``cv2.connectedComponentsWithStats`` 拿每簇像素数，
    仅保留 ≥ ``min_size`` 的簇。

    阈值依据（300 DPI 古籍）：
    - 最小字笔画（点、提）≈ 10-30 px²
    - 标点 `·` `,` ≈ 8-20 px²
    - 尘点 / 飞墨 ≈ 1-3 px²
    - 故 ``min_size=4`` 安全；``min_size=8`` 激进（可能吃小标点）

    只清黑像素（值 0），白像素保持原样。
    """
    if min_size <= 1:
        return arr_u8
    # connectedComponentsWithStats 背景标 0；将背景反转后统计黑像素簇
    # 输入约定：黑=0（文字），白=255（背景）
    # 用 invert 让黑像素成为"前景"
    inv = cv2.bitwise_not(arr_u8)  # 黑→白, 白→黑
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=8)
    # stats[:, cv2.CC_STAT_AREA] 是每簇像素数（含背景 label 0）
    out = arr_u8.copy()
    for label in range(1, n_labels):  # 跳过背景
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_size:
            # 把这簇的像素恢复为白色（arr_u8 中 = 255）
            out[labels == label] = 255
    return out


def _apply_cleanup(arr_u8: np.ndarray, cleanup: str) -> np.ndarray:
    """按 ``cleanup`` 选项对二值化结果做后清理（v2.3.3+）。

    Args:
        arr_u8: 二值化后的 uint8 数组（黑=0，白=255）。
        cleanup: ``none`` / ``morph`` / ``components`` / ``both``。

    Returns:
        清理后的数组（同 dtype）。
    """
    if cleanup == "none" or not cleanup:
        return arr_u8
    if cleanup == "morph":
        return _morph_open(arr_u8, kernel_size=3)
    if cleanup == "components":
        return _drop_small_components(arr_u8, min_size=4)
    if cleanup == "both":
        out = _drop_small_components(arr_u8, min_size=4)
        return _morph_open(out, kernel_size=3)
    raise ValueError(
        f"未知 --binarize-cleanup: {cleanup!r}（合法: {BINARIZE_CLEANUP_CHOICES}）"
    )


# v1.5+ A1：以下 ``*_from_array`` 私有变体接受 ndarray（uint8 或 float32），
# pipeline 在主循环一次 convert("L") 后直接传 arr，免去下游重复转换。
# 公共函数变成薄包装，行为完全一致。


def binarize_otsu_from_array(
    arr: np.ndarray,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """Otsu 核心（v1.5+ A1：接受 ndarray uint8/float32）。

    v2.0+ ``binary_mode``：默认 ``"1bit"`` 返回 ``mode="1"``（1-bit 调色板，
    体积 8x 缩减）；``"8bit"`` 保留 v1.9 行为返回 ``mode="L"``。
    v2.3.3+ ``cleanup``：古籍扫描件噪点清理（``none``/``morph``/``components``/``both``）。
    """
    arr_u8 = arr.astype(np.uint8)
    _threshold, binary = cv2.threshold(arr_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = _apply_cleanup(binary, cleanup)
    return _to_1bit_image(binary) if binary_mode == "1bit" else _to_L_image(binary)


def binarize_adaptive_from_array(
    arr: np.ndarray,
    block_size: int = 31,
    C: int = 10,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """Adaptive 核心（v1.5+ A1：接受 ndarray）。

    v2.0+ 加 ``binary_mode``；v2.3.3+ 加 ``cleanup``。
    """
    arr_u8 = arr.astype(np.uint8)
    binary = cv2.adaptiveThreshold(
        arr_u8,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        C,
    )
    binary = _apply_cleanup(binary, cleanup)
    return _to_1bit_image(binary) if binary_mode == "1bit" else _to_L_image(binary)


def binarize_sauvola_from_array(
    arr: np.ndarray,
    window_size: int = 25,
    k: float = 0.2,
    R: float = 128.0,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """Sauvola 核心（v1.5+ A1：接受 ndarray）。

    输入 dtype 期望 float32（与 ``_to_gray_array`` 一致）；pipeline 在主循环
    ``np.asarray(image.convert("L"), dtype=np.float32)`` 之后调用本函数。

    v1.6+ B3：var / std / multiplier 三步全部原地写到 ``mean_sq`` 缓冲，
    省掉独立的 ``var`` + ``std`` + ``threshold`` 三个 float32 临时数组。
    实测 4000×4000：peak memory 442.6MB → ~210MB（-52%）。

    v2.0+ ``binary_mode``：默认 ``"1bit"`` 返回 ``mode="1"``（1-bit 调色板，
    体积 8x 缩减）；``"8bit"`` 保留 v1.9 行为返回 ``mode="L"``。
    v2.3.3+ ``cleanup``：古籍扫描件噪点清理。
    """
    # 强制奇数窗口
    if window_size % 2 == 0:
        window_size += 1
    ksize = (window_size, window_size)

    # 局部均值 E[X]（float32, alloc 1）
    mean = cv2.boxFilter(arr, -1, ksize)
    # 局部均方 E[X²]（float32, alloc 2）— v1.5+ A2 平台后端
    mean_sq = _local_mean_sq(arr, ksize)

    # v1.6+ B3：var → std → multiplier 三步原地写到 mean_sq。
    # 此后 mean_sq 内存承载 multiplier（不再需要 var / std / threshold）。
    np.subtract(mean_sq, mean * mean, out=mean_sq)  # var = E[X²] - E[X]²
    np.maximum(mean_sq, 0.0, out=mean_sq)            # clip ≥ 0
    np.sqrt(mean_sq, out=mean_sq)                   # std = sqrt(var)
    mean_sq /= R                                    # std / R
    mean_sq -= 1.0                                  # std / R - 1
    mean_sq *= k                                    # k * (std/R - 1)
    mean_sq += 1.0                                  # 1 + k*(std/R - 1)
    # 现在 mean_sq = multiplier

    # threshold = mean * multiplier（1 个 float32 alloc，仍比原版省 2 个）
    threshold = mean * mean_sq
    # 文字通常比背景深，文字像素 < 阈值；因此 THRESH_BINARY_INV
    binary = np.where(arr < threshold, 0, 255).astype(np.uint8)
    binary = _apply_cleanup(binary, cleanup)
    return _to_1bit_image(binary) if binary_mode == "1bit" else _to_L_image(binary)


def binarize_otsu(
    image: Image.Image,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """Otsu 全局阈值二值化。v2.0+ ``binary_mode``；v2.3.3+ ``cleanup``。"""
    return binarize_otsu_from_array(
        _to_gray_array(image), binary_mode=binary_mode, cleanup=cleanup
    )


def binarize_adaptive(
    image: Image.Image,
    block_size: int = 31,
    C: int = 10,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """OpenCV 自适应阈值（高斯加权），适合光照不均的扫描件。

    v2.0+ ``binary_mode``；v2.3.3+ ``cleanup``。
    """
    return binarize_adaptive_from_array(
        _to_gray_array(image),
        block_size=block_size,
        C=C,
        binary_mode=binary_mode,
        cleanup=cleanup,
    )


def binarize_sauvola(
    image: Image.Image,
    window_size: int = 25,
    k: float = 0.2,
    R: float = 128.0,
    binary_mode: BinaryMode = "1bit",
    cleanup: str = "components",
) -> Image.Image:
    """Sauvola 局部自适应二值化（**推荐用于古籍**）。

    对纸张泛黄、不均匀光照等情况效果好。

    后端选择：v1.5+ A2 —— 平台自动 + ``BOOKCUT_BINARIZE`` 环境变量覆盖。

    v1.5+ A1：薄包装，convert("L") 后调 ``binarize_sauvola_from_array``。

    v2.0+ ``binary_mode`` 默认 ``"1bit"`` —— 1-bit 调色板（值 0/1），
    PNG/PDF 体积缩到 8-bit 输出的 1/8；``"8bit"`` 保留 v1.9 行为。

    v2.3.3+ ``cleanup``：古籍扫描件噪点清理（默认 ``components`` = 丢 < 4 px² 黑簇）。

    Args:
        image: 输入图像（任意模式）。
        window_size: 局部窗口大小（奇数），默认 25。
        k: 阈值公式系数，默认 0.2（古籍常用 0.2~0.5）。
        R: 灰度动态范围（0~255），默认 128。
        binary_mode: ``"1bit"`` (默认) 或 ``"8bit"``。
        cleanup: ``"none"`` / ``"morph"`` / ``"components"``（默认）/ ``"both"``。
    """
    return binarize_sauvola_from_array(
        _to_gray_array(image),
        window_size=window_size,
        k=k,
        R=R,
        binary_mode=binary_mode,
        cleanup=cleanup,
    )


def binarize(
    image: Image.Image,
    method: str = "sauvola",
    **kwargs,
) -> Image.Image:
    """二值化分派。

    v2.0+：通过 ``**kwargs`` 透传 ``binary_mode``，默认 ``"1bit"``。
    ``"1bit"`` 模式下输出 ``mode="1"``（值 0/1），体积 8x 缩减。
    ``"8bit"`` 保留 v1.9 行为返回 ``mode="L"``。
    v2.3.3+：新增 ``cleanup`` 透传，默认 ``"components"``（丢小 specks）。
    ``cleanup`` 对 ``method="none"`` 无效（原图直通）。

    Args:
        image: 输入图像。
        method: 'otsu' | 'adaptive' | 'sauvola' | 'none'。
        kwargs: 传递给具体算法的参数（含 ``binary_mode`` / ``cleanup``）。
    """
    method = method.lower()
    if method in ("none", "", "off"):
        return image
    if method == "otsu":
        return binarize_otsu(image, **kwargs)
    if method == "adaptive":
        return binarize_adaptive(image, **kwargs)
    if method == "sauvola":
        return binarize_sauvola(image, **kwargs)
    raise ValueError(f"未知二值化方法: {method}")
