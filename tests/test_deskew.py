"""deskew 测试：用"输出图的直线角度接近 0°"验证校正成功。"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

from book_cut.preprocess.deskew import deskew


def _img_with_border() -> Image.Image:
    """带清晰版框的 800x500 图。"""
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(80, 60), (720, 440)], outline="black", width=3)
    for y in range(80, 420, 30):
        draw.line([(100, y), (700, y)], fill="black", width=2)
    return img


def _rotate(image: Image.Image, angle: float) -> Image.Image:
    return image.rotate(
        angle, resample=Image.BICUBIC, fillcolor="white", expand=True
    )


def _measure_horizontal_angle(image: Image.Image) -> float:
    """测量图像中最近水平线的角度（度）。接近 0 表示线是水平的。"""
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=80,
        minLineLength=max(50, gray.shape[1] // 8),
        maxLineGap=10,
    )
    if lines is None:
        return 999.0
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if a < 0:
            a += 180
        if a > 90:
            a -= 180
        if abs(a) < 5:
            angles.append(a)
    if not angles:
        return 999.0
    return float(np.median(angles))


def test_hough_corrects_positive_rotation():
    img = _img_with_border()
    rotated = _rotate(img, 3.0)
    # 旋转后图内的水平线应有 ~3° 倾角
    pre_angle = _measure_horizontal_angle(rotated)
    assert abs(pre_angle) > 1.5  # 确实有倾斜

    out = deskew(rotated, method="hough")
    post_angle = _measure_horizontal_angle(out)
    # 校正后倾角应 < 0.5°
    assert abs(post_angle) < 0.5, f"residual angle = {post_angle}"


def test_hough_corrects_negative_rotation():
    img = _img_with_border()
    rotated = _rotate(img, -2.5)
    pre_angle = _measure_horizontal_angle(rotated)
    assert abs(pre_angle) > 1.5

    out = deskew(rotated, method="hough")
    post_angle = _measure_horizontal_angle(out)
    assert abs(post_angle) < 0.5, f"residual angle = {post_angle}"


def test_no_op_when_already_aligned():
    img = _img_with_border()
    pre_angle = _measure_horizontal_angle(img)
    out = deskew(img, method="hough")
    post_angle = _measure_horizontal_angle(out)
    assert abs(post_angle) < 0.5
    assert abs(post_angle) <= abs(pre_angle) + 0.1


def test_projection_method():
    img = _img_with_border()
    rotated = _rotate(img, 2.0)
    out = deskew(rotated, method="projection", max_angle=5.0)
    post_angle = _measure_horizontal_angle(out)
    # 投影法精度略低，放宽到 0.8°
    assert abs(post_angle) < 0.8, f"residual angle = {post_angle}"


def test_auto_handles_borderless():
    """无版框时 auto 应回退到 projection。"""
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    for y in range(40, 380, 30):
        for x in range(40, 580, 30):
            draw.line([(x, y), (x + 15, y)], fill="black", width=2)
    rotated = _rotate(img, 2.0)
    out = deskew(rotated, method="auto", max_angle=5.0)
    assert isinstance(out, Image.Image)
    assert out.size[0] > 0


def test_invalid_method_raises():
    img = _img_with_border()
    import pytest

    with pytest.raises(ValueError):
        deskew(img, method="bogus")
