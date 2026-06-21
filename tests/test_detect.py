"""detect 模块测试：trim + border + paper。"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from book_cut.detect.border import crop_to_border
from book_cut.detect.paper import (
    CropConfig,
    adaptive_padding,
    aggregate_paper_color,
    default_crop_config,
    estimate_paper_color,
)
from book_cut.detect.trim import trim_margins


def _page_with_white_margins() -> Image.Image:
    """合成一张 600x400 的单页：白边 + 黑边框 + 文字。"""
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    # 版框 (80,60) - (520,340)
    draw.rectangle([(80, 60), (520, 340)], outline="black", width=3)
    # 文字行
    for y in range(80, 320, 30):
        draw.line([(100, y), (500, y)], fill="black", width=2)
    return img


def _page_with_heavy_white_margins() -> Image.Image:
    """四周有明显白边的图。"""
    img = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(img)
    # 内容集中在中间 200x150
    for y in range(80, 220, 25):
        draw.line([(100, y), (300, y)], fill="black", width=2)
    return img


def test_trim_cuts_white_margins():
    img = _page_with_heavy_white_margins()
    out = trim_margins(img, padding=2)
    # 输出应比原图小
    assert out.size[0] < img.size[0]
    assert out.size[1] < img.size[1]


def test_trim_keeps_content_box():
    """trim 应切到内容外边界 + padding。"""
    img = _page_with_white_margins()
    out = trim_margins(img, padding=5)
    # 版框在 (80,60)-(520,340)，外加 padding 5
    # 输出应大致是这个范围
    w, h = out.size
    assert w == 520 - 80 + 1 + 2 * 5
    assert h == 340 - 60 + 1 + 2 * 5


def test_border_crops_inside_frame():
    img = _page_with_white_margins()
    out = crop_to_border(img, padding=2)
    # 版框在 (80,60)-(520,340)，内含 padding 约 2
    # 输出应大致是这个范围
    w, h = out.size
    assert w <= 520 - 80 + 4
    assert h <= 340 - 60 + 4
    assert w > 100  # 不能裁没了


def test_border_fallback_to_trim():
    """没有明显版框时回退到 trim。"""
    img = _page_with_heavy_white_margins()
    # 这里没有连续版框线，应回退到 trim
    out = crop_to_border(img)
    assert out.size != img.size  # 应有裁切


# ============ paper color & adaptive crop 测试 (v1.3) ============


def test_paper_color_estimator_white_image():
    """纯白图 → 255.0 (clipped 95th percentile)."""
    img = Image.new("RGB", (300, 200), "white")
    assert estimate_paper_color(img) == 255.0


def test_paper_color_estimator_yellowed_paper():
    """灰度 200 的"泛黄"纸 → ~195 (clip 下限 180)."""
    arr = np.full((200, 300), 200, dtype=np.uint8)
    img = Image.fromarray(arr, mode="L")
    val = estimate_paper_color(img)
    assert 180.0 <= val <= 200.0


def test_paper_color_estimator_robust_to_dense_ink():
    """半白半黑（模拟 ZHSY cover）→ 255.0 (95th percentile 仍是白)."""
    arr = np.full((200, 300), 255, dtype=np.uint8)
    arr[:, 150:] = 0  # 右半全黑
    img = Image.fromarray(arr, mode="L")
    assert estimate_paper_color(img) == 255.0


def test_aggregate_paper_color_median_robust_to_outlier():
    """一页异常值不应拉低书级 paper color."""
    colors = [240.0, 245.0, 248.0, 250.0, 100.0]  # 100 是 cover 异常
    assert aggregate_paper_color(colors) == 245.0  # median


def test_aggregate_paper_color_empty():
    """空列表兜底 255.0."""
    assert aggregate_paper_color([]) == 255.0


def test_aggregate_paper_color_single():
    """单元素直接返回."""
    assert aggregate_paper_color([233.5]) == 233.5


def test_adaptive_padding_scaling():
    """按尺寸缩放: 700→14, 1500→30 (cap), 4000→30 (cap), 100→5 (floor)."""
    assert adaptive_padding(700, 700) == 14  # int(700*0.02)=14
    assert adaptive_padding(1500, 1500) == 30  # int(1500*0.02)=30, cap
    assert adaptive_padding(4000, 4000) == 30  # int(4000*0.02)=80, clamp to 30
    assert adaptive_padding(100, 100) == 5  # int(100*0.02)=2, floor


def test_default_crop_config_ink_threshold():
    """ink_threshold = max(paper_color - ink_offset, 60)."""
    c = CropConfig(paper_color=240.0, ink_offset=30.0)
    assert c.ink_threshold == 210.0
    # 极低 paper 不应塌缩
    c2 = CropConfig(paper_color=50.0, ink_offset=30.0)
    assert c2.ink_threshold == 60.0


def test_default_crop_config_factory():
    """default_crop_config: 显式 paper_color 时直接用；None 时用 240."""
    assert default_crop_config().paper_color == 240.0
    assert default_crop_config(245.0).paper_color == 245.0
    assert default_crop_config(None).paper_color == 240.0


# ----- v1.5+ per-page override -----


def test_should_override_at_threshold():
    """偏离 == 阈值 → 触发 override（>= 边界）。"""
    from book_cut.detect.paper import should_override

    # 偏离 30 == 阈值 30 → True
    assert should_override(per_paper=250, book_paper=220, threshold=30) is True


def test_should_override_below_threshold():
    """偏离 < 阈值 → 不 override。"""
    from book_cut.detect.paper import should_override

    assert should_override(per_paper=245, book_paper=220, threshold=30) is False  # 25 < 30


def test_should_override_exact_match():
    """偏离 0 → 不 override。"""
    from book_cut.detect.paper import should_override

    assert should_override(per_paper=220, book_paper=220, threshold=30) is False


def test_should_override_force_per_page():
    """threshold=0 → 强制每页 override。"""
    from book_cut.detect.paper import should_override

    assert should_override(per_paper=180, book_paper=220, threshold=0) is True


def test_should_override_disable():
    """threshold=999 → 永不 override（v1.3 等价行为）。"""
    from book_cut.detect.paper import should_override

    assert should_override(per_paper=180, book_paper=255, threshold=999) is False


def test_estimate_paper_color_from_array():
    """``estimate_paper_color_from_array`` 跳过 PIL，直接消费 ndarray。"""
    from book_cut.detect.paper import estimate_paper_color_from_array

    # 灰度 200 的"泛黄"纸
    arr = np.full((200, 300), 200, dtype=np.uint8)
    val = estimate_paper_color_from_array(arr)
    assert 180.0 <= val <= 200.0

    # 纯白
    arr_white = np.full((100, 100), 255, dtype=np.uint8)
    assert estimate_paper_color_from_array(arr_white) == 255.0


def test_estimate_paper_color_from_array_empty():
    """空数组 → 255.0 兜底。"""
    from book_cut.detect.paper import estimate_paper_color_from_array

    arr = np.array([], dtype=np.uint8)
    assert estimate_paper_color_from_array(arr) == 255.0


def test_per_page_override_resolves_correctly(tmp_path):
    """端到端：构造一个 book 模拟纸色 + 单页异常纸色，验证 override 触发。

    Book paper = 220（采样页都是 220）
    Page 5 = 180（黄页）→ 偏离 40 ≥ 30 → override 用 per-page config
    """
    import argparse

    import pymupdf
    from PIL import Image

    from book_cut.pipeline import run_pipeline

    # 合成 5 页 PDF：前 4 页纸色 220（白偏黄），第 5 页纸色 180（黄）
    png_pages = []
    for i in range(5):
        # page i+1: 前 4 是 220，page 5 是 180
        paper = 220 if i < 4 else 180
        arr = np.full((500, 800), paper, dtype=np.uint8)
        # 加几条墨迹（避免 trim 失败）
        arr[100:120, 100:700] = 30
        img = Image.fromarray(arr, mode="L")
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_pages.append(buf.getvalue())

    doc = pymupdf.open()
    for png in png_pages:
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png)
    in_pdf = tmp_path / "mixed_paper.pdf"
    doc.save(str(in_pdf))
    doc.close()

    out_dir = tmp_path / "out"
    args = argparse.Namespace(
        input=str(in_pdf), output=str(out_dir),
        split="half", crop="trim", binarize="none",
        deskew=False, auto_single_page=True, page_order="ltr", outline=True,
        format="png", crop_adaptive="auto", paper_pages=4, paper_deviation=30,
        half_offset=0, pdf=False,
    )

    run_pipeline(args)
    # 5 页 × 2 (half 切) = 10 张
    out_files = sorted(out_dir.glob("*.png"))
    assert len(out_files) == 10


def test_per_page_override_disabled_at_999():
    """--paper-deviation 999 → 永不 override（等同 v1.3 行为）。"""
    import argparse
    from io import BytesIO
    from pathlib import Path

    import pymupdf
    from PIL import Image

    from book_cut.pipeline import run_pipeline
    arr = np.full((500, 800), 220, dtype=np.uint8)
    arr[100:120, 100:700] = 30
    img = Image.fromarray(arr, mode="L")
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=800, height=500)
        page.insert_image(page.rect, stream=png_bytes)
    in_pdf = Path("/tmp/zzz_no_override.pdf")
    doc.save(str(in_pdf))
    doc.close()

    out_dir = Path("/tmp/zzz_no_override_out")
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    out_dir.mkdir()

    args = argparse.Namespace(
        input=str(in_pdf), output=str(out_dir),
        split="half", crop="trim", binarize="none",
        deskew=False, auto_single_page=True, page_order="ltr", outline=True,
        format="png", crop_adaptive="auto", paper_pages=2, paper_deviation=999,
        half_offset=0, pdf=False,
    )

    run_pipeline(args)
    out_files = sorted(out_dir.glob("*.png"))
    assert len(out_files) == 6


# ----- trim_margins 自适应模式测试 -----


def test_trim_adaptive_matches_fixed_on_white_paper():
    """白底/黑墨 fixture：adaptive 与 fixed 输出尺寸完全相同 (回归钉子)."""
    img = _page_with_white_margins()
    fixed = trim_margins(img, padding=5)
    adaptive = trim_margins(
        img,
        config=CropConfig(paper_color=255.0, padding=5, min_edge_ink=3),
    )
    assert adaptive.size == fixed.size


def test_trim_adaptive_handles_yellowed_paper():
    """灰墨 80 + 黄纸 200：fixed (thr=240) 把纸误当内容，adaptive (thr=170) 正确."""
    arr = np.full((300, 400), 200, dtype=np.uint8)  # 黄纸
    # 内部画一个 80 灰的"内容框"
    arr[80:220, 100:300] = 80
    img = Image.fromarray(arr, mode="L")

    fixed = trim_margins(img, padding=2)  # thr=240, 200<240 → 把整个纸当内容
    adaptive = trim_margins(
        img,
        config=CropConfig(paper_color=200.0, padding=2, min_edge_ink=3),
    )  # thr=170, 200>170 → 纸正确判为纸
    # adaptive 应裁得更小（紧贴内容框），fixed 会保留更多黄色"内容"
    assert adaptive.size[0] < fixed.size[0] or adaptive.size[1] < fixed.size[1]


def test_border_fallback_uses_adaptive_config():
    """border 检测失败回退到 trim 时也要用 adaptive config."""
    # 用 _page_with_heavy_white_margins：内容在中间，无明显版框矩形，
    # border 检测必失败，触发 trim fallback
    img = _page_with_heavy_white_margins()
    cfg = CropConfig(paper_color=240.0, padding=2, min_edge_ink=3)
    adaptive = crop_to_border(img, config=cfg)
    expected = trim_margins(img, config=cfg)
    assert adaptive.size == expected.size


# ============ D3：border 路径完整覆盖（v1.5 Sprint 1 防回归） ============


def test_border_fallback_when_no_lines_detected():
    """``_detect_lines`` 返 None → fallback 到 trim.

    构造纯白图（无任何边 → Canny 空 → Hough 空 → return None）。
    """
    img = Image.new("RGB", (600, 400), "white")
    # 加一点纯文字避免 trim 也跑出空（trim 走 paper-color-based 检测）
    draw = ImageDraw.Draw(img)
    for y in range(80, 320, 30):
        draw.line([(100, y), (500, y)], fill="black", width=2)

    out = crop_to_border(img, padding=2)
    # border 检测不到 → fallback trim → 输出比原图小（裁到内容）
    assert out.size != img.size
    assert out.size[0] < img.size[0]


def test_border_fallback_when_only_one_vertical(monkeypatch):
    """``_detect_lines`` 返 (1 竖, N 横) → fallback 到 trim."""
    import book_cut.detect.border as border_mod

    # monkeypatch _detect_lines：只返 1 个竖线簇（< 2）
    def fake_detect(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
        return ([100], [50, 100, 150, 200, 250, 300, 350])  # 只有 1 个竖线簇

    monkeypatch.setattr(border_mod, "_detect_lines", fake_detect)

    img = _page_with_white_margins()  # 有清晰版框，但被 mock 掉了
    out = crop_to_border(img, padding=2)

    # fallback 到 trim → 输出有内容（不是空 / 不是原图大小）
    expected = trim_margins(img, padding=2)
    assert out.size == expected.size


def test_border_fallback_when_only_one_horizontal(monkeypatch):
    """``_detect_lines`` 返 (N 竖, 1 横) → fallback 到 trim."""
    import book_cut.detect.border as border_mod

    def fake_detect(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
        return ([100, 200, 300, 400, 500], [200])  # 只有 1 个横线簇

    monkeypatch.setattr(border_mod, "_detect_lines", fake_detect)

    img = _page_with_white_margins()
    out = crop_to_border(img, padding=2)

    expected = trim_margins(img, padding=2)
    assert out.size == expected.size


def test_border_fallback_when_bbox_too_small(monkeypatch):
    """``_detect_lines`` 返的 bbox < 20% 图像尺寸 → fallback 到 trim."""
    import book_cut.detect.border as border_mod

    def fake_detect(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
        # bbox (10, 10) - (50, 50) → 40x40，远小于 600x400 的 20%（120x80）
        return ([10, 50], [10, 50])

    monkeypatch.setattr(border_mod, "_detect_lines", fake_detect)

    img = _page_with_white_margins()
    out = crop_to_border(img, padding=2)

    # fallback 到 trim
    expected = trim_margins(img, padding=2)
    assert out.size == expected.size


def test_split_border_then_crop_border_chain():
    """``--split border --crop border`` 联动：Hough 跑两次但结果都对。

    验证：split_border 输出 2 张带边框的子图，crop_to_border 各自裁到版框内部。
    """
    from book_cut.split.border import split_border

    # 800x500 双版框图（复用 conftest 的 fixture pattern）
    img = Image.new("RGB", (800, 500), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(80, 60), (380, 440)], outline="black", width=2)
    draw.rectangle([(420, 60), (720, 440)], outline="black", width=2)
    for y in range(100, 400, 40):
        draw.line([(100, y), (360, y)], fill="black", width=2)
        draw.line([(440, y), (700, y)], fill="black", width=2)

    # split: 2 张子图
    sub_pages = split_border(img)
    assert len(sub_pages) == 2

    # crop: 每张裁到自己的版框内
    cropped = [crop_to_border(p, padding=2) for p in sub_pages]
    for c in cropped:
        # 输出应比 split 的子图小（裁掉了边）
        assert c.size[0] <= 350  # 380-80+2*2 = 304，但 Hough 可能略有偏差
        assert c.size[1] <= 400
