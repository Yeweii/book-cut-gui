# book-cut

古籍双页扫描切分工具 —— 把两页合一的扫描件拆成单页，可选二值化、版框内裁/白边裁切、倾斜校正、合并 PDF。

## 特性

- **输入**：PDF（多页）/ 单图 / 嵌套图片文件夹
- **三种切分策略**（CLI / GUI 切换）：
  - `gutter`（默认）—— 列投影找中缝，最白连续段中心，鲁棒性最好
  - `border` —— Hough 直线检测版框，按版框中心切分
  - `half` —— 固定对半切（支持 `--half-offset N` 微调）
- **可选处理**：
  - 倾斜校正 `--deskew`（Hough 法默认，找不到时回退投影法）
  - 单页裁切 `--crop {none,trim,border}`：trim=白边裁切，border=版框内裁（找不到版框自动回退 trim）
  - 二值化 `--binarize {none,otsu,adaptive,sauvola}`，Sauvola 默认（最适合古籍泛黄/不均光照）
- **输出**：`{book}_{idx:04d}.{ext}`（png/jpg/tif/webp）+ 可选 `--pdf` 合并 PDF（img2pdf 无损）
- **GUI**：Tkinter 单窗口（macOS 自动用 aqua 主题）+ 后台线程 + 实时日志
- 流水线：`load → deskew → split → crop → binarize → export`

## 安装

需要 Python 3.11+（开发用 3.11.15，跨 macOS / Windows）。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

> 国内网络 pip 慢可加清华源：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...`

## 用法

### CLI

```bash
# 中缝切分 + Sauvola 二值化 + 输出 PDF（最常用）
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola --pdf

# 版框线切分，JPG 输出
python -m book_cut -i ./scans -o ./out --split border --format jpg

# 对半切（带 5px 偏移）
python -m book_cut -i page.jpg -o ./out --split half --half-offset 5

# 倾斜校正 + 切白边 + 版框内裁（综合示例）
python -m book_cut -i scan.pdf -o ./out --deskew --split gutter --crop border --binarize sauvola --pdf

# 启动 GUI
python -m book_cut --gui
```

### CLI 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `-i / --input` | 必填 | 输入：PDF / 图片 / 文件夹 |
| `-o / --output` | 必填 | 输出目录 |
| `--deskew` | 关 | 倾斜校正（Hough，fallback 投影） |
| `--split` | `gutter` | `half` / `gutter` / `border` |
| `--crop` | `none` | `none` / `trim`（白边）/ `border`（版框内裁） |
| `--binarize` | `none` | `none` / `otsu` / `adaptive` / `sauvola` |
| `--half-offset` | `0` | 对半切的像素偏移（仅 `--split half` 生效） |
| `--format` | `png` | `png` / `jpg` / `tif` / `webp` |
| `--pdf` | 关 | 同时输出合并 PDF |
| `--gui` | 关 | 启动 GUI |

### Python API

```python
from book_cut.io.loader import iter_pages
from book_cut.preprocess.deskew import deskew
from book_cut.preprocess.binarize import binarize
from book_cut.split.gutter import split_gutter

for page in iter_pages("book.pdf"):
    img = deskew(page.image)              # 倾斜校正
    left, right = split_gutter(img)        # 中缝切分
    left = binarize(left, "sauvola")       # 二值化
    left.save(f"{page.source_name}_L.png")
    right.save(f"{page.source_name}_R.png")
```

## 推荐配方（古籍）

```bash
# 版面整齐的现代古籍扫描
python -m book_cut -i book.pdf -o out --split gutter --crop trim --binarize sauvola --pdf

# 扫描有轻微倾斜 + 有版框
python -m book_cut -i book.pdf -o out --deskew --split border --crop border --binarize sauvola --pdf

# 漫漶 / 无版框古籍（用中缝 + Sauvola）
python -m book_cut -i book.pdf -o out --deskew --split gutter --binarize sauvola --pdf
```

## 自适应裁切（v1.3+）

切白边（`--crop trim`）与版框内裁（`--crop border`）的 fallback 现在**默认按纸张色自适应**：

- 用 PDF 前 N 页（默认 5）估计"书级纸张色"
- 自适应墨迹阈值 = `paper_color − 30`（下限 60）
- 自适应 padding = `max(短边 × 2%, 5)`，clamp ≤ 30
- 边缘"有内容"判定 ≥ 3 个 ink 像素（抗 JPEG 噪声）

古籍泛黄/泛灰（paper median 200-220）时，旧硬编码 `threshold=240` 会把纸当内容、留下黄边；
自适应会**更紧致地切到真正内容**。在 `ZHSY100456_醉翁琴趣外篇`（66 页，paper p95=218）上：

| 模式 | 图数 | 平均尺寸 | 总输出大小 | 耗时 |
|------|------|----------|------------|------|
| `--crop-adaptive fixed` (v1.1) | 132 | 515×790 | 2.7M | 2.82s |
| `--crop-adaptive auto` (v1.3) | 132 | 469×688 | 2.6M | 2.86s |

CLI 开关：

```bash
# 显式切回 v1.1 行为
python -m book_cut -i book.pdf -o out --crop trim --crop-adaptive fixed

# 改采样页数（混合纸张的书可加大）
python -m book_cut -i book.pdf -o out --crop trim --paper-pages 10
```

GUI 在"单页裁切"行多了 **自适应（按纸色）** 复选框（默认勾选）+ **采样页** spinner。

## 项目结构

```
src/book_cut/
├── cli.py                # argparse 入口
├── pipeline.py           # load → deskew → split → crop → binarize → export
├── gui.py                # Tkinter GUI
├── io/
│   ├── loader.py         # PDF / 图片 / 文件夹 → PageInfo 流
│   └── exporter.py       # 图片保存 + 合并 PDF
├── split/                # 三种切分策略
│   ├── half.py
│   ├── gutter.py
│   └── border.py
├── detect/               # 单页裁切
│   ├── trim.py           # 白边
│   └── border.py         # 版框内裁
└── preprocess/           # 图像预处理
    ├── binarize.py       # Otsu / Adaptive / Sauvola
    └── deskew.py         # Hough / 投影
```

## 开发

```bash
.venv/bin/pytest                  # 跑全部 36 个测试
.venv/bin/pytest --cov=book_cut   # 覆盖率
.venv/bin/ruff check src tests    # 静态检查
.venv/bin/python scripts/make_sample.py samples/sample_two_page.png   # 生成测试图
```

## 打包成 macOS .app

把 GUI 打成双击可运行的 `.app`，分发给无 Python 环境的同事：

```bash
bash packaging/build_macos.sh       # 约 1-2 分钟，输出 dist/Book Cut.app (~220MB)
open "dist/Book Cut.app"            # 启动 GUI
```

**架构**：默认 arm64（Apple Silicon）。给 Intel Mac 用需在 Intel 上重跑同一脚本。
**签名**：未做 codesign / notarize（需 Apple Developer 账号）。首次双击会被 Gatekeeper 拦截：
- 右键 → "打开" → "仍要打开"，或
- `xattr -d com.apple.quarantine "dist/Book Cut.app"`

详细打包说明、前置条件、验证清单、常见问题见 [`docs/packaging.md`](docs/packaging.md)。

## 路线图

v1.2 (2026-06-21)：PyInstaller 打包成 macOS .app，双击启动 GUI。

未来可选：
- 自动 OCR 识别书名
- 倾斜方向自适应（自动选 Hough vs 投影）
- 切分质量评估（基于文本行完整性）
- Deep learning 版框检测

## 许可

MIT
