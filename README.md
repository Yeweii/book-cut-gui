# book-cut

古籍双页扫描切分工具 —— 把两页合一的扫描件拆成单页，可选二值化、版框内裁/白边裁切、倾斜校正、合并 PDF。

## 特性

- **输入**：PDF（多页）/ 单图 / 嵌套图片文件夹
- **三种切分策略**（CLI / GUI 切换）：
  - `gutter`（默认）—— 列投影找中缝，最白连续段中心，鲁棒性最好
  - `border` —— Hough 直线检测版框，按版框中心切分
  - `half` —— 固定对半切（支持 `--half-offset N` 微调）
  - `manual`（v2.4+）—— 用户画一条切分线，整本书复用（古籍装订物理位置固定）
- **可选处理**：
  - 倾斜校正 `--deskew`（Hough 法默认，找不到时回退投影法）
  - 单页裁切 `--crop {none,trim,border}`：trim=白边裁切，border=版框内裁（找不到版框自动回退 trim）
  - 二值化 `--binarize {none,otsu,adaptive,sauvola}`，Sauvola 默认（最适合古籍泛黄/不均光照）
  - 图片预处理 `--preprocess "sharpen,denoise,clahe,gamma"`（v1.9+；4 个独立 op 链式应用，fast/balanced/best 三档）
- **输出**：`{book}_{idx:04d}.{ext}`（png/jpg/tif/webp）+ 可选 `--pdf` 合并 PDF（img2pdf 无损）
- **GUI**：Tkinter 单窗口（macOS 自动用 aqua 主题）+ 后台线程 + 实时日志 + **停止按钮**（v1.8.1+ 长跑可随时取消）
- 流水线：`load → preprocess → deskew → split → crop → binarize → export`

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
| `--split` | `gutter` | `half` / `gutter` / `border` / `manual`（v2.4+）/ `none` |
| `--manual-split-x` | 无 | v2.4+：手动切分 x 坐标（原图坐标系，1 ≤ x < W）。需配合 `--split manual` |
| `--manual-split-preset` | 无 | v2.4+：手动切分 JSON preset 路径（v1 schema），与 `--manual-split-x` 同给时 preset 优先 |
| `--pick-split-line` | 关 | v2.4+ 子命令：弹 GUI 选切分线，写入 JSON 到 `-o`。用法：`python -m book_cut --pick-split-line -i book.pdf -o preset.json` |
| `--crop` | `none` | `none` / `trim`（白边）/ `border`（版框内裁） |
| `--binarize` | `none` | `none` / `otsu` / `adaptive` / `sauvola` |
| `--binary-mode` | `1bit` | v2.0+：二值化输出位深 `1bit`（1-bit 调色板，PNG/PDF 体积 ~30% 缩）/ `8bit`（8-bit L，向后兼容）。可被 `BOOKCUT_BINARY_MODE` 环境变量覆盖 |
| `--half-offset` | `0` | 对半切的像素偏移（仅 `--split half` 生效） |
| `--format` | `png` | `png` / `jpg` / `tif` / `webp` |
| `--pdf` | 关 | 同时输出合并 PDF |
| `--page-order` | `ltr` | 1:2 切分时输出顺序：`ltr`=左先右后 / `rtl`=右先左后（古籍竖排常用） |
| `--no-outline` | 关 | 关闭 PDF outline（书签）/ metadata 透传（仅 `--pdf` 模式有效；兜底用） |
| `--pdf-page-size` | `keep` | PDF 页面统一尺寸（v1.7+；仅 `--pdf` 模式有效）：`keep`=保持原图 / `max`=所有页 max(W)×max(H) / `first`=首页 / `a4` / `a5` / `letter` / `legal` / `custom`（配 `--pdf-page-dim` + `--pdf-page-unit`） |
| `--pdf-page-dim` | 无 | 自定义尺寸 `WxH`（如 `280x200`；仅 `--pdf-page-size custom`） |
| `--pdf-page-unit` | `mm` | 自定义尺寸单位 `mm` / `cm` / `inch` / `px`（仅 custom） |
| `--dry-run` | 关 | 预览模式（v1.8+）：不写实际输出，仅跑前 N 页出对比图 + 指标 JSON。写盘 flag 全部 warn 后忽略 |
| `--sample-n` | `3` | dry-run 采样页数（仅 `--dry-run` 生效；最小 1） |
| `--preview-output` | 系统 tmpdir | 预览输出目录（仅 `--dry-run` 生效） |
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

## PDF outline / metadata 保留（v1.4+）

当输入是 PDF 且开了 `--pdf` 时，book-cut 默认**把原 PDF 的 outline（书签）和 metadata（标题/作者等）透传到输出 PDF**：

- outline 1:2 时**只指第一张**（LTR 指左，RTL 指右）—— 第二张不挂 outline 节点
- 嵌套层级完整保留（卷 → 章 → 节）
- metadata `Title/Author/Subject/Keywords/Creator` 一股脑透传；`Producer` 追加 `book-cut 0.1.6` 标记出处
- 多 PDF 源（文件夹内多 PDF）只保留**第一个 PDF** 的 outline + metadata（v1.5 再做合并）
- 纯图片输入无 outline 处理（无原 PDF 可参考）

```bash
# 默认：保留 outline + metadata
python -m book_cut -i book.pdf -o out --split gutter --binarize sauvola --pdf

# 关闭透传（兜底）
python -m book_cut -i book.pdf -o out --pdf --no-outline

# 繁体竖排古籍：用 rtl 让右页先出
python -m book_cut -i 醉翁琴趣.pdf -o out --split gutter --pdf --page-order rtl
```

GUI 在"输出格式"行多了 **页序** 下拉（**先左后右** / **先右后左**）+ **保留书签** 复选框（默认勾选）。GUI 显示用中文，CLI 仍用 `ltr/rtl`。

实现：img2pdf 出无 outline 中间 PDF → pypdf 后处理注入 outline + metadata → 覆盖。复用 img2pdf 的"无损"特性，新增依赖只有 ~1MB 的纯 Python `pypdf`。

## PDF 页面统一尺寸（v1.7+）

当输入是扫描件（PDF / 嵌套图片）且开了 `--pdf` 时，book-cut 默认让**每页 page size 用图原分辨率**——结果同本书内封面 3708×3862、文本 3424×3330、插图页 4288×3330，PDF 阅读器里每页大小都不同，缩放阅读体验差。`--pdf-page-size` 选项解决此问题：

- `keep`（默认）= 保持 v1.6 行为，零侵入
- `max` = 预扫所有输入页取 `max(W) × max(H)`（PDF 133 页 < 100ms 流式）
- `first` = 首页尺寸
- `a4` / `a5` / `letter` / `legal` = 标准预设
- `custom` = 自定义（`--pdf-page-dim 280x200 --pdf-page-unit mm`）

实现：在每张子图保存前，等比 fit + 居中 paste 到目标 `(W, H)` 画布（留白填白）。`img2pdf` 默认按 96 DPI 把像素换算到 points（A4 794×1123 px → 595.5×842.25 pt，PDF 阅读器标准 A4）。

```bash
# 全部页统一到 A4（古籍按 A4 打印友好）
python -m book_cut -i book.pdf -o out --split gutter --binarize sauvola --pdf --pdf-page-size a4

# 取所有页 max(W)×max(H)（保证图不被放大）
python -m book_cut -i book.pdf -o out --split border --pdf --pdf-page-size max

# 自定义 280×200 mm（仿古线装书）
python -m book_cut -i book.pdf -o out --split gutter --pdf \
    --pdf-page-size custom --pdf-page-dim 280x200 --pdf-page-unit mm
```

**作用域**：仅 `--pdf` 模式生效；非 PDF 模式 → 警告后忽略（图片输出保持原分辨率）。GUI 在"输出格式"下一行多了 **PDF 页面尺寸** 下拉 + 选 `自定义` 时启用 W/H/unit 三个输入框；PDF checkbox 关闭 → 整行 disable。

## Dry-Run 预览模式（v1.8+）

调参时不再"盲跑 130 页 20 秒"—— `--dry-run` 走前 N 页（默认 3）全流水线，输出**对比拼图 + 指标 JSON**：

```bash
# 启用 dry-run + 默认采样 3 页
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola --dry-run

# 显式指定采样数 + 预览输出位置
python -m book_cut -i book.pdf -o ./out --dry-run --sample-n 5 --preview-output ./preview

# 与现有调参 flag 全兼容
python -m book_cut -i book.pdf -o ./out --dry-run --sample-n 3 \
    --deskew --split border --crop border --binarize sauvola
```

| 新增 flag | 默认 | 说明 |
|-----------|------|------|
| `--dry-run` | 关 | 启用预览模式；不写真图/PDF |
| `--sample-n N` | 3 | 采样页数（PDF = 前 N 页 / 文件夹 = 前 N 文件 / 单图 = N=1 自动） |
| `--preview-output DIR` | 系统 tmpdir `book-cut-preview-<ts>` | 预览图 + JSON 落盘位置 |

**作用域规则**：
- `--dry-run` 开启 → `--pdf` / `--format` / `--pdf-page-size` / `--no-outline` 等**写盘 flag** 全部 warn 后忽略
- `output` 目录**不会被创建**（避免污染用户文件系统）
- 预览目录默认在系统 tmpdir，带时间戳避免冲突

**输出结构**：
```
book-cut-preview-20260623-153022/
├── preview_p0001_compare.png   # 第 1 页对比拼图
├── preview_p0002_compare.png
├── preview_p0003_compare.png
├── preview_summary.json        # 汇总 + 调参建议
└── README.txt
```

**对比拼图**：3 列（原图 | L | R）并排，红色虚线标记 split column。等高对齐 + 总宽 ≤ 6000px。

**指标 JSON**：每页 split confidence / crop boxes / binarize params / timings_ms / warnings，外加 `suggestion` 字段（自动调参建议，例 "page 2 confidence 0.42 偏低，建议 --split border"）。

GUI：在"二值化"行右侧加 **Dry-run 预览（不写盘）** checkbox + **采样: N 页** spinner；勾选时整张"输出格式"行 disable；执行后 **打开预览目录** 按钮 enable。

### v1.8.1 GUI 停止按钮

"开始处理"按钮旁加 **停止** 按钮（默认 disabled）：运行中可按下优雅取消 —— 取消时**单页计算保持原子性**（在页边界检查），不写半截 PDF，已生成的图保留。

## 图片预处理增强（v1.9+）

古籍扫描件常因保存条件差、扫描参数不一出现**墨迹模糊 / 纸张污渍 / 光照不均 / 整体偏暗**。v1.9+ 在 **deskew 之前** 加 4 个独立的可选信号级增强：

| op | 解决 | 算法 |
|----|------|------|
| `sharpen` | 笔画模糊 | Unsharp Mask（cv2 / PIL） |
| `denoise` | 1-3 px 尘点、扫描噪点 | fast: PIL GaussianBlur；balanced: bilateralFilter；best: NL-Means |
| `clahe` | 泛黄纸、光照不均 | cv2.createCLAHE 局部直方图均衡 |
| `gamma` | 深底封面 / 过曝 | 伽马校正（γ<1 提亮，γ>1 压暗） |

### CLI 用法

```bash
# 启用锐化（默认 balanced 档）
python -m book_cut -i book.pdf -o ./out --preprocess "sharpen"

# 推荐链：denoise → clahe → sharpen
python -m book_cut -i book.pdf -o ./out --preprocess "denoise=7,clahe=2.0,sharpen=1.5"

# 质量档：fast（PIL 内置，零 OpenCV） / balanced（cv2 中等，默认） / best（cv2 高质量）
python -m book_cut -i book.pdf -o ./out --preprocess "denoise" --preprocess-quality best

# 伽马：深底封面用 γ<1 提亮
python -m book_cut -i cover.jpg -o ./out --split half --preprocess "gamma=0.7"
```

### 语法

`--preprocess` 接受**逗号分隔的链**（按声明顺序应用），每个 token 可选 `=value` 覆盖默认参数：

| token | 默认（balanced） | 说明 |
|-------|------------------|------|
| `sharpen` / `sharp` | amount=1.5 | 锐化强度（0=原图，1=典型，2=强） |
| `denoise` / `dn` | h=7 | NL-Means 强度 / bilateral sigma |
| `clahe` / `cl` | clip=2.0 | 对比度限制（古籍泛黄常用 2.0~3.0） |
| `gamma` / `gm` | γ=1.2 | 伽马值（γ<1 提亮，γ>1 压暗；clamp [0.25, 4.0]） |

**推荐顺序**：denoise → clahe → sharpen → gamma（先清噪再展对比再锐化最后调亮度）。

### 质量档性能（4000×4000 灰度，全 4 op 链）

| 档位 | 耗时 | 用途 |
|------|------|------|
| `fast` | ~110ms | 批量处理（NL-Means 太重的场景） |
| `balanced` | ~180ms | **默认推荐**，bilateralFilter 边缘保留 |
| `best` | ~850ms | 一次性精扫，NL-Means 全搜索 |

环境变量 `BOOKCUT_PREPROCESS_QUALITY=fast|balanced|best` 可覆盖默认值。

### dry-run 集成

`--dry-run --preprocess ...` 自动出 **4 联对比图**：`[原始 RGB] | [preprocess 后] | [deskew 后] | [最终 binarize 后]`。

### GUI

在"输出格式"行下方加 **图像增强** 控件：preset combobox（none / sharpen / denoise / clahe / ... 7 种 + custom）+ 质量 combobox（fast/balanced/best）+ 自定义链 entry（仅 custom 时 enable）。

## 手动切分线（v2.4+）

`--split manual` 适用于自动切分（gutter / border）失败的古籍扫描：书脊歪斜、扫描偏色导致中缝最白段不明显、版框断裂等场景。

**两阶段用法**：

```bash
# 第一步：弹 GUI 选切分线 → 保存为 preset
python -m book_cut --pick-split-line -i book.pdf -o preset.json
# GUI 内拖一条竖直线到中缝位置，点「确定」即写入 preset.json

# 第二步：用 preset 跑流水线
python -m book_cut -i book.pdf -o ./out --split manual --manual-split-preset preset.json
# 或直接给 x（无 preset）：
python -m book_cut -i book.pdf -o ./out --split manual --manual-split-x 970
```

**关键约束**：
- `--deskew` 状态必须与创建 preset 时一致；不一致会触发 **MS009** 错误（preset 在 post-deskew 坐标系下，--deskew 切换会改变坐标系 → 切分 x 偏移）
- `--split manual` 单页检测时跳过（warn MS007；古籍单页本身就一页，不需要切）
- GUI 主窗切到「手动（画线）」radio 时，「选切分线...」按钮自动启用

详见 `samples/crop_profiles/v2_manual_split_example.json`。

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
.venv/bin/pytest                  # 跑全部 213 个测试
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

- v1.8.2 (2026-06-23)：trim 安全 margin 二级 fallback + 稀疏墨迹保护（裁剪效果差修复）
- v1.8.1 (2026-06-23)：GUI 停止按钮 + 后端 `cancel_event` 透传（主循环 + dry-run）
- v1.8 (2026-06-23)：Dry-run 预览模式 `--dry-run` / `--sample-n` / `--preview-output`；对比拼图 + split confidence + 自动调参建议
- v1.7 (2026-06-22)：PDF 页面统一尺寸 `--pdf-page-size`（max/first/A4/A5/Letter/Legal/custom）
- v1.6 (2026-06-22)：split-crop 抗伤字/抗杂质；Hough 缓存联动（A3）；Sauvola 原地写（B3）；pipeline 拆 3 模块（C3）；paper/trim 共享 utils（C2）；GUI UX 改进（E1+E3）
- v1.5 (2026-06-21)：per-page paper color override；流式 iter_pages（O(N×page) → O(page)）；outline 注入全内存
- v1.4 (2026-06-21)：PDF outline / metadata 透传；新增 `--page-order` + `--no-outline`
- v1.3 (2026-06-21)：自适应裁切（按书级纸张色学习阈值）
- v1.2 (2026-06-21)：PyInstaller 打包成 macOS .app

未来可选：
- v1.9 候选：summary.suggestion 智能化（基于 confidence + paper color 偏差 + crop box 长宽比异常 → 自动建议下轮调参）；GUI 拼图内嵌预览
- v2 候选：方向 padding（天/地/内/外）；自动 OCR 识别书名；Deep learning 版框检测；Windows .exe 打包

## 许可

MIT
