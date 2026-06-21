"""生成一张模拟古籍双页扫描的合成图，用于端到端测试。"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def make_sample(out_path: Path, w: int = 1200, h: int = 1600) -> Path:
    """模拟古籍双页：左右各一个版框，中间版心线带竖行文字。"""
    img = Image.new("RGB", (w, h), (240, 232, 215))  # 泛黄纸色
    draw = ImageDraw.Draw(img)

    # 随机噪点模拟纸张纹理
    random.seed(42)
    for _ in range(w * h // 200):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        v = random.randint(180, 240)
        draw.point((x, y), fill=(v, v - 5, v - 15))

    # 左右版框
    box_top, box_bottom = 80, h - 80
    left_box = (60, box_top, w // 2 - 30, box_bottom)
    right_box = (w // 2 + 30, box_top, w - 60, box_bottom)
    for box in (left_box, right_box):
        draw.rectangle(box, outline=(20, 20, 20), width=3)

    # 装订线（细竖线）
    draw.line([(w // 2, 60), (w // 2, h - 60)], fill=(120, 100, 80), width=2)

    # 用默认字体写一些"文字"行（横线模拟）
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 14)
    except OSError:
        font = ImageFont.load_default()

    line_y = box_top + 30
    for box in (left_box, right_box):
        y = line_y
        for _ in range(35):
            # 每行画 12~18 条短横线
            n = random.randint(12, 18)
            x = box[0] + 20
            for _i in range(n):
                seg = random.randint(8, 20)
                draw.line(
                    [(x, y), (x + seg, y)],
                    fill=(20, 20, 20),
                    width=2,
                )
                x += seg + random.randint(4, 10)
            y += 32
            if y > box[3] - 30:
                break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples/sample_two_page.png")
    p = make_sample(out)
    print(f"Generated: {p} ({p.stat().st_size} bytes)")
