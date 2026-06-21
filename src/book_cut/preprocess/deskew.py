"""倾斜校正（deskew）：检测并旋转扫描件到正方向。

提供两种方法：
- hough：基于 Hough 直线检测 + 角度中位数（适合有清晰版框的扫描件）
- projection：基于水平投影方差（适合无版框、纯文字扫描件）
- auto：优先 hough，无直线时回退 projection

v1.5+ A1：``deskew_from_array`` 私有变体接受 ndarray，pipeline 跳过重复 ``convert("L")``。
旋转用 cv2.warpAffine（替代 PIL.rotate），行为等价：``expand=True`` + 白底。
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def _to_gray_array(image: Image.Image) -> np.ndarray:
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.uint8)


def _to_L_image(arr_u8: np.ndarray) -> Image.Image:
    return Image.fromarray(arr_u8, mode="L")


def _rotate(image: Image.Image, angle: float, background: int = 255) -> Image.Image:
    """绕中心旋转，PIL 在白底上旋转避免黑边。"""
    if abs(angle) < 0.05:
        return image
    return image.rotate(
        angle,
        resample=Image.BICUBIC,
        fillcolor=(background,) * len(image.getbands()),
        expand=True,
    )


def _rotate_array(arr: np.ndarray, angle: float, background: int = 255) -> np.ndarray:
    """绕中心旋转 ndarray，expand=True 等价（容纳旋转后内容），白底（v1.5+ A1）。

    cv2.warpAffine 等价 PIL.rotate(..., expand=True)：
    1. 计算 expand 后的画布尺寸
    2. 平移旋转中心到新画布中心
    3. warpAffine 用 INTER_CUBIC + borderValue=255
    """
    if abs(angle) < 0.05:
        return arr
    h, w = arr.shape
    abs_cos = abs(np.cos(np.radians(angle)))
    abs_sin = abs(np.sin(np.radians(angle)))
    new_w = int(np.ceil(h * abs_sin + w * abs_cos))
    new_h = int(np.ceil(h * abs_cos + w * abs_sin))
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2
    rotated = cv2.warpAffine(
        arr, M, (new_w, new_h), flags=cv2.INTER_CUBIC, borderValue=background
    )
    return np.ascontiguousarray(rotated)


# ----------------------------------------------------------------------------
# Hough 法
# ----------------------------------------------------------------------------


def _detect_angle_hough(gray: np.ndarray, max_angle: float = 5.0) -> float | None:
    """用 Hough 直线找主角度（接近 0° 的水平线）。返回角度（度）。"""
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(30, gray.shape[1] // 20),
        maxLineGap=10,
    )
    if lines is None:
        return None

    angles: list[float] = []
    for x1, y1, x2, y2 in lines[:, 0]:
        # 只关心接近水平的线（接近 0° 或 180°）
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if a < 0:
            a += 180
        if a > 90:
            a -= 180
        if abs(a) <= max_angle:
            angles.append(a)

    if len(angles) < 3:
        return None
    return float(np.median(angles))


# ----------------------------------------------------------------------------
# 投影法
# ----------------------------------------------------------------------------


def _binarize_for_projection(gray: np.ndarray) -> np.ndarray:
    """为投影方差计算做快速二值化。"""
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return b


def _detect_angle_projection(gray: np.ndarray, max_angle: float = 5.0) -> float | None:
    """用水平投影方差最大原则找旋转角。

    两遍搜索：粗搜 1° 步长 → 精搜 0.1° 步长。
    """
    binary = _binarize_for_projection(gray)
    h, w = binary.shape

    def score(angle: float) -> float:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(
            binary, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0
        )
        proj = rotated.sum(axis=1).astype(np.float64)
        return float(proj.var())

    # 粗搜
    coarse_angles = np.arange(-max_angle, max_angle + 0.5, 1.0)
    coarse_scores = [score(a) for a in coarse_angles]
    best_idx = int(np.argmax(coarse_scores))
    best_coarse = coarse_angles[best_idx]

    # 精搜（±1° 范围，0.1° 步长）
    fine_angles = np.arange(best_coarse - 1.0, best_coarse + 1.05, 0.1)
    fine_scores = [score(a) for a in fine_angles]
    best = float(fine_angles[int(np.argmax(fine_scores))])

    return best


# ----------------------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------------------


def deskew_from_array(
    arr: np.ndarray,
    method: str = "auto",
    max_angle: float = 5.0,
) -> np.ndarray:
    """倾斜校正核心（v1.5+ A1：接受 ndarray，返回 ndarray）。

    pipeline 在主循环 convert("L") 后调本函数。返回的 ndarray 可能是不同尺寸
    （旋转时 expand=True 等价），下游需按 arr 路径继续。
    """
    method = method.lower()

    if method == "hough":
        angle = _detect_angle_hough(arr, max_angle)
    elif method == "projection":
        angle = _detect_angle_projection(arr, max_angle)
    elif method == "auto":
        angle = _detect_angle_hough(arr, max_angle)
        if angle is None:
            angle = _detect_angle_projection(arr, max_angle)
    else:
        raise ValueError(f"未知 deskew 方法: {method}")

    if angle is None or abs(angle) < 0.1:
        return arr

    # 校正：detected 是图像坐标下"线相对水平方向"的角度（Y-down 坐标）。
    # 直接把 detected 作为 cv2.warpAffine 的角度即可让线回正（符号巧合地一致）。
    return _rotate_array(arr, angle)


def deskew(
    image: Image.Image,
    method: str = "auto",
    max_angle: float = 5.0,
) -> Image.Image:
    """倾斜校正。

    v1.5+ A1：薄包装，convert("L") 后调 ``deskew_from_array``，结果包回 Image。

    Args:
        image: 输入图像。
        method: 'hough' | 'projection' | 'auto'。
        max_angle: 搜索的最大角度（度），默认 5°。
    """
    arr = _to_gray_array(image)
    out = deskew_from_array(arr, method=method, max_angle=max_angle)
    return _to_L_image(out)
