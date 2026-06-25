# Book Cut 使用手册

> 古籍双页扫描切分工具 —— 把两页合一的扫描件拆成单页，可选二值化、白边裁切、版框内裁、倾斜校正、合并 PDF。

- **当前版本**：v0.3.1（v2.3 独立奇偶页裁切） · 2026-06-25
- **目标用户**：古籍数字化工作者、出版社、图书馆员、个人藏书数字化
- **支持平台**：macOS（arm64 / x86_64）、Linux、Windows（Python 3.11+）
- **GitHub**：本地仓库

---

## 目录

- [1. 快速开始](#1-快速开始)
- [2. 安装](#2-安装)
- [3. 核心概念](#3-核心概念)
- [4. CLI 命令行使用](#4-cli-命令行使用)
  - [4.1 基础用法](#41-基础用法)
  - [4.2 切分策略详解](#42-切分策略详解)
  - [4.3 裁切模式](#43-裁切模式)
  - [4.4 手动裁切（v2.3+ 重点）](#44-手动裁切v23-重点)
  - [4.5 倾斜校正与预处理](#45-倾斜校正与预处理)
  - [4.6 二值化](#46-二值化)
  - [4.7 PDF 输出与排版选项](#47-pdf-输出与排版选项)
  - [4.8 Dry-run 预览调参](#48-dry-run-预览调参)
  - [4.9 完整参数表](#49-完整参数表)
- [5. GUI 图形界面使用](#5-gui-图形界面使用)
  - [5.1 启动](#51-启动)
  - [5.2 界面布局](#52-界面布局)
  - [5.3 工作流：典型 5 步操作](#53-工作流典型-5-步操作)
  - [5.4 手动裁切拖框（v2.3 重点）](#54-手动裁切拖框v23-重点)
  - [5.5 停止与取消](#55-停止与取消)
- [6. 推荐配方（古籍场景）](#6-推荐配方古籍场景)
- [7. 常见问题 FAQ](#7-常见问题-faq)
- [8. 故障排查](#8-故障排查)
- [9. 高级用法（Python API / 打包）](#9-高级用法python-api--打包)

---

## 1. 快速开始

**两分钟跑通第一条命令**（macOS / Linux 终端）：

```bash
# 1) 进入项目
cd /path/to/book-cut

# 2) 准备虚拟环境（一次性）
python3.11 -m venv .venv
source .venv/bin/activate

# 3) 安装
pip install -r requirements.txt
pip install -e .

# 4) 跑一条最常用的命令：中缝切分 + Sauvola 二值化 + 输出 PDF
python -m book_cut -i samples/尸子卷上下.浙江书局.光绪三年刊.pdf \
                   -o ./out \
                   --split gutter \
                   --binarize sauvola \
                   --pdf
```

输出结构：

```
out/
├── 尸子卷上下.浙江书局.光绪三年刊_0001.png   # 第 1 张（左页）
├── 尸子卷上下.浙江书局.光绪三年刊_0002.png   # 第 2 张（右页）
├── 尸子卷上下.浙江书局.光绪三年刊_0003.png
├── ...
└── 尸子卷上下.浙江书局.光绪三年刊.pdf      # 合并 PDF
```

> **Windows 用户**：激活 venv 改用 `\.venv\Scripts\activate`，其余命令一致。

---

## 2. 安装

### 2.1 系统要求

| 项目 | 要求 |
|------|------|
| Python | 3.11 或更高（开发用 3.11.15） |
| 操作系统 | macOS 12+ / Ubuntu 20.04+ / Windows 10+ |
| 内存 | 建议 ≥ 4 GB（处理 4000×4000 灰度图） |
| 磁盘 | ≥ 1 GB 可用空间（含 .venv） |

### 2.2 标准安装（开发者）

```bash
# 克隆代码（已是本地仓库时跳过）
git clone <repo-url> book-cut
cd book-cut

# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .\.venv\Scripts\activate         # Windows

# 升级 pip + 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
pip install -e ".[dev]"            # 含 pytest / ruff / pyinstaller
```

**国内网络慢时**加清华源：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### 2.3 终端用户安装（仅用 CLI / GUI，不需要测试）

```bash
pip install -e .
# 启动 GUI
python -m book_cut --gui
```

### 2.4 macOS .app 打包版（推荐给非技术同事）

把整个项目打成双击可运行的 `.app`：

```bash
bash packaging/build_macos.sh       # 约 1-2 分钟
open "dist/Book Cut.app"            # 启动 GUI
```

产物：`dist/Book Cut.app`（约 238 MB，arm64 / Apple Silicon）。

> **首次双击会被 Gatekeeper 拦截**，任选一种方式放行：
> - 右键 → "打开" → "仍要打开"
> - 或在终端执行：`xattr -d com.apple.quarantine "dist/Book Cut.app"`

---

## 3. 核心概念

在阅读后续章节前，先理解 5 个核心概念：

### 3.1 流水线（Pipeline）

book-cut 把一本书的每一页依次经过 7 个步骤：

```
load → preprocess → deskew → split → crop → binarize → export
```

| 步骤 | 作用 | 默认 | 关闭方式 |
|------|------|------|----------|
| **load** | 读 PDF / 图片 / 扫描文件夹为 PageInfo 流 | 必跑 | — |
| **preprocess** | 锐化 / 去噪 / 直方图均衡 / 伽马 | 关 | 不传 `--preprocess` |
| **deskew** | 倾斜校正（Hough 法，fallback 投影法） | 关 | 不传 `--deskew` |
| **split** | 把"双页"切成 2 张子图（中缝 / 版框 / 对半 / 不切） | `gutter` | `--split none` |
| **crop** | 单页裁切（白边 / 版框内裁 / 手动 / 不裁） | `none` | `--crop none` |
| **binarize** | 二值化（Otsu / Adaptive / Sauvola） | `none` | `--binarize none` |
| **export** | 写盘为 png/jpg/tif/webp + 可选 PDF | 必跑 | — |

### 3.2 切分策略（Split）

| 策略 | 说明 | 适用 |
|------|------|------|
| `gutter` | **默认**。列投影找中缝：最白连续段中心。鲁棒性最好 | 90% 的古籍 |
| `border` | Hough 直线检测版框，按版框中心切 | 有清晰版框的现代排版 |
| `half` | 固定对半切（支持 `--half-offset N` 像素微调） | 扫描严格居中 |
| `none` | **不切分**。输入已是单页 | 单页扫描件 |

### 3.3 裁切模式（Crop）

| 模式 | 说明 | 算法 |
|------|------|------|
| `none` | **默认**。不裁 | — |
| `trim` | 切白边（自适应 paper color） | trim 算法（形态学 + CCA） |
| `border` | 版框内裁（找不到版框自动回退 trim） | Hough + CCA |
| `manual` | **手动裁切**（v2.2+；v2.3 独立奇偶） | 用户给的 4 个 padding |

### 3.4 奇偶页（Odd / Even Page）

古籍双页扫描件切分后产生 2 张子图：

```
┌─────────────────────┬─────────────────────┐
│   左 物 理 页        │   右 物 理 页        │
│   (verso / 偶页)    │   (recto / 奇页)    │
│   中缝在右            │   中缝在左            │
└─────────────────────┴─────────────────────┘
                ↑
              split 切分线
```

- **奇页（odd, recto）**：右半张，**中缝在左**（gutter 左，外侧右）
- **偶页（even, verso）**：左半张，**中缝在右**（gutter 右，外侧左）

**v2.3 关键变更**：奇偶页可独立指定 padding，不再强制镜像。

### 3.5 输出编号

- 计数器从 1 开始（`0001`, `0002`, ...）
- 1:2 切分时，先输出 `--page-order` 决定的那一侧（LTR = 左先 / RTL = 右先）
- 文件名格式：`{book_name}_{idx:04d}.{ext}`

---

## 4. CLI 命令行使用

### 4.1 基础用法

#### 4.1.1 输入输出

```bash
# 必填参数
-i / --input     # 输入：PDF / 单图 / 文件夹
-o / --output    # 输出目录（不存在会自动创建）
```

```bash
# 单图输入
python -m book_cut -i scan.png -o ./out --split half

# PDF 输入
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola

# 文件夹输入（递归扫描所有 png/jpg/tif/webp）
python -m book_cut -i ./scans_folder -o ./out --split gutter
```

#### 4.1.2 输出格式

```bash
--format png      # 默认；无损，体积大
--format jpg      # 有损，体积小
--format tif      # 无损，适合再处理
--format webp     # 现代格式，压缩比高
```

#### 4.1.3 同时输出合并 PDF

```bash
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola --pdf
# 输出：每页 PNG + 一个 book.pdf（img2pdf 无损）
```

### 4.2 切分策略详解

#### 4.2.1 `gutter`（默认，最常用）

```bash
python -m book_cut -i book.pdf -o ./out --split gutter
```

原理：
1. 灰度化图像
2. 列方向加和（每列的"白度"）
3. 找最白的连续段（默认宽度 ≥ 5 px）
4. 取该段中心作为切分线

适用：90% 的古籍、装订成册的扫描件。

#### 4.2.2 `border`（版框线）

```bash
python -m book_cut -i book.pdf -o ./out --split border
```

原理：Hough 直线检测找出版框，按版框中心切分。
适用：有清晰版框的现代排版（如新印古籍排印本）。

#### 4.2.3 `half`（对半切）

```bash
# 标准对半
python -m book_cut -i page.jpg -o ./out --split half

# 偏移 5 像素（扫描略偏右时往左偏 5 px）
python -m book_cut -i page.jpg -o ./out --split half --half-offset -5
```

适用：扫描严格居中（否则会出现"左宽右窄"或反之）。

#### 4.2.4 `none`（不切分）

```bash
# 输入已是单页扫描件
python -m book_cut -i single_page.png -o ./out --split none --crop trim
```

适用：单独扫描的单页 PDF/图。

### 4.3 裁切模式

#### 4.3.1 `none`（不裁）

```bash
python -m book_cut -i book.pdf -o ./out --split gutter    # 默认
```

#### 4.3.2 `trim`（白边裁切）

```bash
# 基础白边裁切
python -m book_cut -i book.pdf -o ./out --split gutter --crop trim

# 完整配方：倾斜校正 + 自适应 trim + Sauvola 二值化
python -m book_cut -i book.pdf -o ./out \
    --deskew --split gutter --crop trim --binarize sauvola --pdf
```

**trim 自适应参数**：

```bash
--crop-adaptive auto     # 默认；按纸张色自适应（古籍泛黄友好）
--crop-adaptive fixed    # v1.1 行为；硬编码阈值 240
--paper-pages 5          # 采样页数（学习书级 paper color）
--paper-deviation 30     # per-page paper color override 阈值
```

**trim 高级调参**（v2.1+）：

```bash
# 抗 paper color 估计偏差：用二值化结果当 ink mask
--crop trim --trim-source binarized

# 抗 1-3 px 尘点 / 折痕：CCA 主体过滤
--crop trim --trim-min-component-ratio 0.001

# 版心保护区：保留鱼尾 / 边栏（不被 CCA 滤掉）
--crop trim --trim-min-component-ratio 0.001 --trim-gutter-band "0.4,0.6"

# 多带豁免：双页扫描 + 右侧副页保留
--crop trim --trim-min-component-ratio 0.001 --trim-gutter-bands "0.4,0.5,0.7,0.9"

# 后置过滤：排除页眉/页脚稀疏行
--crop trim --trim-source binarized --trim-strict

# adaptive padding 覆盖：设 0=完全贴 bbox；设 50=加保护边
--crop trim --adaptive-padding 0
--crop trim --adaptive-padding 50

# 版框检测（v2.1+ E2）：古籍版框页专用
--crop trim --trim-frame
```

**形态学开关**：

```bash
# 默认开：抗 1-3 px 尘点 / 折痕
# 关掉：古籍飞白 / 6pt 注疏等极小字（1-2 px 笔画）保留
--no-morph
```

#### 4.3.3 `border`（版框内裁）

```bash
python -m book_cut -i book.pdf -o ./out \
    --split border --crop border --binarize sauvola --pdf
```

找不到版框时自动回退 `trim`。

#### 4.3.4 `manual`（手动裁切）

详见 [§4.4 手动裁切](#44-手动裁切v23-重点)。

### 4.4 手动裁切（v2.3+ 重点）

**为什么需要手动？** 古籍常有鱼尾、版心装饰、版框残缺、扫描倾斜等，auto 算法可能误判。手动裁切让你**对每张子图精确指定 4 个 padding**。

#### 4.4.1 4 个 padding 含义

```
        top
    ┌─────────────┐
    │             │
← I │  content   │ O →
    │             │
    └─────────────┘
       bottom
```

- **T (top)**：从顶部裁掉多少 px
- **B (bottom)**：从底部裁掉多少 px
- **I (inner)**：中缝侧裁掉多少 px
  - 奇页（gutter 在左）= 左边
  - 偶页（gutter 在右）= 右边
- **O (outer)**：外侧裁掉多少 px
  - 奇页 = 右边
  - 偶页 = 左边

**关键公式**（v2.3+）：

| 奇偶 | 切分公式 |
|------|----------|
| 奇页（recto） | `arr[top:H-bottom, inner:W-outer]` |
| 偶页（verso） | `arr[top:H-bottom, outer:W-inner]` |

#### 4.4.2 奇页 / 偶页独立指定

```bash
# 完整示例：奇偶页 padding 不同
python -m book_cut -i book.pdf -o ./out \
    --split gutter \
    --crop manual \
    --manual-odd-padding "T=50,B=40,I=80,O=30" \
    --manual-even-padding "T=50,B=40,I=30,O=80"
```

- 奇页：pad 顶 50、底 40、左 80、右 30
- 偶页：pad 顶 50、底 40、左 30、右 80（**注意 inner/outer 互换**）

#### 4.4.3 两种语法格式

```bash
# 位置式：顺序固定 T,B,I,O
--manual-odd-padding "50,40,80,30"

# 键值式：顺序任意
--manual-odd-padding "T=50,B=40,I=80,O=30"
```

#### 4.4.4 单页输入（`--split none`）

当输入是单页扫描件时，book-cut 用**全局页号**判定奇偶（1-based）：

| 全局页号 | 奇偶 | 使用的 profile |
|----------|------|----------------|
| 1, 3, 5, ... | 奇 | `odd_page` |
| 2, 4, 6, ... | 偶 | `even_page` |

这与 `page_order` 无关（单页无 page_order 概念）。

#### 4.4.5 Preset 复用（JSON）

**保存 preset**：

```bash
python -m book_cut -i book.pdf -o ./out \
    --crop manual \
    --manual-odd-padding "T=50,B=40,I=80,O=30" \
    --manual-even-padding "T=50,B=40,I=30,O=80" \
    --manual-save-preset ./my_profile.json
```

**加载 preset**（预设优先于 `--manual-*`）：

```bash
python -m book_cut -i another_book.pdf -o ./out \
    --crop manual \
    --manual-preset ./my_profile.json
```

**preset 文件格式**（v2.3+ v2 schema）：

```json
{
  "version": 2,
  "odd_page": {
    "top": 50,
    "bottom": 40,
    "inner": 80,
    "outer": 30
  },
  "even_page": {
    "top": 50,
    "bottom": 40,
    "inner": 30,
    "outer": 80
  },
  "source_size": [4947, 7610],
  "notes": "鱼尾不对称场景的独立 padding"
}
```

#### 4.4.6 向后兼容（v1 preset 自动迁移）

v2.3+ 自动从 v1 preset 迁移：

| v1 preset | 迁移结果 |
|-----------|----------|
| `{"top":50, "bottom":40, "inner":80, "outer":30, "mirror_even":true}` | odd = (50,40,80,30)，even = (50,40,30,80) |
| `{"top":50, ..., "mirror_even":false}` | odd = even = (50,40,80,30) |

旧 JSON 文件不会被修改，新 `to_json()` 始终输出 v2 格式。

#### 4.4.7 已废弃参数

`--manual-mirror-even` 在 v2.3+ 已废弃。仍传值时**会被忽略并 warn**，请改用 `--manual-even-padding`：

```bash
# v2.2（旧）：
python -m book_cut ... --manual-odd-padding "T=50,B=40,I=80,O=30" --manual-mirror-even
# 偶页自动 inner↔outer 镜像 → (50,40,30,80)

# v2.3+（新）：
python -m book_cut ... \
    --manual-odd-padding "T=50,B=40,I=80,O=30" \
    --manual-even-padding "T=50,B=40,I=30,O=80"  # 显式指定，更准确
```

### 4.5 倾斜校正与预处理

#### 4.5.1 倾斜校正 `--deskew`

```bash
python -m book_cut -i book.pdf -o ./out --deskew --split gutter
```

- 算法：Hough 直线（找不到时回退投影法）
- 自动检测角度（-30° ~ +30°）
- 在 `split` 之前执行

#### 4.5.2 图像预处理 `--preprocess`（v1.9+）

4 个独立 op 链式应用，**在 deskew 之前**：

| op | 解决 | 默认参数（balanced） |
|----|------|---------------------|
| `sharpen` | 笔画模糊 | amount=1.5 |
| `denoise` | 1-3 px 尘点、扫描噪点 | h=7 |
| `clahe` | 泛黄纸、光照不均 | clip=2.0 |
| `gamma` | 深底封面 / 过曝 | γ=1.2 |

**链语法**（按声明顺序应用，可覆盖参数）：

```bash
# 基础链
python -m book_cut -i book.pdf -o ./out --preprocess "sharpen"

# 推荐链：denoise → clahe → sharpen
python -m book_cut -i book.pdf -o ./out --preprocess "denoise=7,clahe=2.0,sharpen=1.5"

# 深底封面：gamma 提亮
python -m book_cut -i cover.jpg -o ./out --split half --preprocess "gamma=0.7"

# 全 4 op 链
python -m book_cut -i book.pdf -o ./out --preprocess "denoise=7,clahe=2.0,sharpen=1.5,gamma=1.2"
```

**质量档**：

```bash
--preprocess-quality fast       # PIL 内置，零 OpenCV（约 110 ms / 页）
--preprocess-quality balanced   # 默认，cv2 中等（约 180 ms / 页）
--preprocess-quality best       # cv2 高质量，NL-Means（约 850 ms / 页）
```

可用环境变量覆盖默认：`export BOOKCUT_PREPROCESS_QUALITY=fast`

**推荐顺序**：`denoise → clahe → sharpen → gamma`（先清噪再展对比再锐化最后调亮度）。

### 4.6 二值化

#### 4.6.1 算法选择

| 算法 | 适用 | 说明 |
|------|------|------|
| `otsu` | 双峰直方图、清晰对比 | 最快，泛黄古籍易把纸当内容 |
| `adaptive` | 局部不均光照 | 中等速度 |
| `sauvola` | **古籍泛黄 / 漫漶** | **默认推荐**，对 paper color 鲁棒 |

```bash
# 泛黄古籍标准配方
python -m book_cut -i book.pdf -o ./out \
    --deskew --split gutter --binarize sauvola --pdf

# 黑白对比强烈的现代印刷
python -m book_cut -i book.pdf -o ./out \
    --split border --binarize otsu --pdf
```

#### 4.6.2 输出位深 `--binary-mode`（v2.0+）

```bash
--binary-mode 1bit   # 默认；1-bit 调色板（PNG/PDF 体积 ~30% 缩）
--binary-mode 8bit   # 8-bit 灰度（v1.9 行为，向后兼容）
```

**性能对比**（6400×8534 尸子图 split=none）：

| 模式 | PDF 体积 | 缩减 |
|------|----------|------|
| 8-bit L（v1.9） | 651 KB | 1.00× |
| 1-bit + Flate | 459 KB | **1.42×** |

可用环境变量覆盖：`export BOOKCUT_BINARY_MODE=8bit`

#### 4.6.3 扫描件噪点清理 `--binarize-cleanup`（v2.3.3+）

古籍扫描件常见"飞墨"（雕版墨渣 / 印刷毛刺）、纸张老化斑点、传感器噪点。Sauvola 等局部阈值会保留这些孤立小簇，二值图上表现为字外散落的黑点。

```bash
--binarize-cleanup components   # 默认（最安全，推荐古籍）
--binarize-cleanup none         # 不清理（旧行为）
--binarize-cleanup morph        # 形态学开运算（去 specks，但 1px 笔画会变细）
--binarize-cleanup both         # components + morph
```

| 模式 | 做法 | 影响 | 适用 |
|------|------|------|------|
| `components`（默认） | 丢 < 4 px² 的黑色连通簇 | **只去飞墨，笔画不变** | **古籍通用**（绣像 / 文字 / 版框） |
| `morph` | 3×3 形态学开运算 | 1px 笔画变细 / 极细末梢丢失 | 笔画粗（>3px）的现代印刷 |
| `both` | 先 components 再 morph | 双重清理 | 噪点极端严重 |
| `none` | 不清理 | 保留所有 specks | 极精细笔画 / 想手动后处理 |

**实测对比**（绣像红楼梦 0007.png, 1920×1664）：

| 模式 | 黑像素总数 | 孤立 specks (1-3 px²) | 笔画影响 |
|------|-----------|---------------------|---------|
| `none` | 421,326 | **955** | 完整 |
| `components`（默认） | 420,371 (-0.2%) | **0** | **完整** ✓ |
| `morph` | 331,357 (**-21%**) | 0 | **丢 90K 像素 / 吃字** |
| `both` | ≈ morph | 0 | ≈ morph（吃字） |

**结论**：`components` 是"白送"的去噪收益——自动清掉 955 个尘点而不动笔画，**默认开启**。`morph` 对古籍风险大（吃细笔画），**不推荐**。

GUI：二值化区多出 `清理` combobox，默认 `components`。

### 4.7 PDF 输出与排版选项

#### 4.7.1 页序 `--page-order`

```bash
--page-order ltr    # 默认；先左后右
--page-order rtl    # 先右后左（古籍竖排常用）
```

仅在 1:2 切分时生效。手动裁切 / `--split none` 时不影响。

#### 4.7.2 保留书签（outline）

```bash
# 默认：保留原 PDF 的 outline（书签）和 metadata
python -m book_cut -i book.pdf -o ./out --pdf

# 关闭透传
python -m book_cut -i book.pdf -o ./out --pdf --no-outline
```

行为：
- outline 1:2 时**只指第一张**（LTR 指左，RTL 指右）
- 嵌套层级完整保留（卷 → 章 → 节）
- metadata（Title / Author / Subject / Keywords / Creator）透传
- `Producer` 字段追加 `book-cut 0.1.6` 标记出处
- 多 PDF 源（文件夹内多 PDF）只保留第一个 PDF 的 outline

#### 4.7.3 PDF 页面统一尺寸 `--pdf-page-size`（v1.7+）

古籍扫描件各页分辨率往往不一致（封面 3708×3862、文本 3424×3330、插图页 4288×3330），输出 PDF 在阅读器里每页大小都不同。此选项统一尺寸：

```bash
--pdf-page-size keep    # 默认；保持原图分辨率
--pdf-page-size max     # 所有页 max(W)×max(H)
--pdf-page-size first   # 首页尺寸
--pdf-page-size a4      # A4（595.5×842.25 pt @ 96 DPI）
--pdf-page-size a5      # A5
--pdf-page-size letter  # Letter
--pdf-page-size legal   # Legal
--pdf-page-size kpw6    # Kindle Paperwhite 6（6.8" E Ink Carta 1200，v2.3.3+）
--pdf-page-size custom  # 自定义（需 --pdf-page-dim + --pdf-page-unit）
```

**电子书导出**（v2.3.3+）：将古籍扫描件直接输出为 Kindle / 电子阅读器原生页面尺寸：

| preset | 尺寸 (mm) | 等效 px @ 96 DPI | 适配设备 |
|--------|----------:|----------------:|---------|
| `kpw6` | 139.5 × 104.3 | 527 × 394 | Amazon Kindle Paperwhite 6（11 代，2021 年）6.8" E Ink Carta 1200 @ 300 ppi（display 区域 1648×1232 px） |

```bash
# 输出 PDF 直接发到 Kindle（横屏，便于双页合并）
python -m book_cut -i book.pdf -o ./out --split gutter --pdf --pdf-page-size kpw6
```

**自定义**：

```bash
# 仿古线装书 280×200 mm
python -m book_cut -i book.pdf -o ./out --split gutter --pdf \
    --pdf-page-size custom --pdf-page-dim 280x200 --pdf-page-unit mm
```

**作用域**：仅 `--pdf` 模式生效；非 PDF 模式 → 警告后忽略。

### 4.8 Dry-run 预览调参

#### 4.8.1 是什么

不再"盲跑 130 页 20 秒"——`--dry-run` 走前 N 页（默认 3）全流水线，输出**对比拼图 + 指标 JSON**，**不写真图 / PDF**。

```bash
# 启用 dry-run
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola --dry-run

# 显式指定采样数 + 预览输出位置
python -m book_cut -i book.pdf -o ./out \
    --dry-run --sample-n 5 --preview-output ./preview
```

#### 4.8.2 输出结构

```
preview/
├── preview_p0001_compare.png     # 第 1 页对比拼图
├── preview_p0002_compare.png
├── preview_p0003_compare.png
├── preview_summary.json          # 汇总 + 调参建议
└── README.txt
```

**对比拼图**（启用 `--preprocess` 时为 4 列）：

```
[原图] | [preprocess 后] | [deskew 后] | [L 子图] | [R 子图]
                          + 红色虚线标记 split column
```

**指标 JSON**（`preview_summary.json`）：包含
- `total_pages` / `sampled_pages` / `sample_indices`
- `config`（当前所有 flag）
- `elapsed_ms`（每页各步耗时 + 估算全本）
- `paper_color_estimate`
- `pages[]`（每页的 `split_confidence` / `crop_boxes` / `binarize_params` / `warnings`）
- `suggestion`（**自动调参建议**，例 "page 2 confidence 0.42 偏低，建议 --split border"）

#### 4.8.3 写盘 flag 互斥

`--dry-run` 开启时，**写盘相关 flag 全部 warn 后忽略**：

```bash
python -m book_cut -i book.pdf -o ./out --dry-run --pdf
# [WARN] --dry-run 模式忽略 --pdf
```

受影响的 flag：`--pdf` / `--format` / `--pdf-page-size` / `--no-outline`。

**`output` 目录不会被创建**（避免污染用户文件系统）。

#### 4.8.4 GUI 联动

GUI 在"二值化"行右侧加 **Dry-run 预览（不写盘）** checkbox + **采样: N 页** spinner；勾选时整张"输出格式"行 disable；执行后 **打开预览目录** 按钮 enable。

### 4.9 完整参数表

#### 4.9.1 必填参数

| 参数 | 说明 |
|------|------|
| `-i / --input` | 输入路径：PDF / 图片 / 文件夹 |
| `-o / --output` | 输出目录 |
| `--gui` | 启动 GUI（替代 `-i` `-o`） |

#### 4.9.2 切分 / 裁切参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--deskew` | 关 | 倾斜校正（Hough，fallback 投影） |
| `--split {none,half,gutter,border}` | `gutter` | 切分策略 |
| `--no-single-page` | 开 | 关闭单页自动检测（强制对半切） |
| `--half-offset N` | `0` | 对半切像素偏移（仅 `--split half`） |
| `--crop {none,trim,border,manual}` | `none` | 单页裁切模式 |
| `--crop-adaptive {auto,fixed}` | `auto` | 裁切阈值策略 |
| `--paper-pages N` | `5` | 学习书级 paper color 的采样页数 |
| `--paper-deviation N` | `30` | per-page paper override 阈值 |
| `--no-morph` | 关 | 关闭 trim 形态学（古籍飞白用） |

#### 4.9.3 Trim 高级调参（v2.1+）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--trim-source {gray,binarized}` | `gray` | ink mask 来源 |
| `--trim-min-component-ratio F` | `0.0` | CCA 主体过滤阈值（>0 启用） |
| `--trim-padding N` | `0` | adaptive padding 之上额外叠加 |
| `--trim-gutter-band "L,R"` | 无 | 单版心带 |
| `--trim-gutter-bands "L1,R1,..."` | 无 | 多版心带 |
| `--trim-strict` | 关 | 排除稀疏行（页眉/页脚） |
| `--adaptive-padding N` | None | 覆盖 adaptive 公式 |
| `--trim-frame` | 关 | 版框检测（古籍版框页） |
| `--trim-frame-min-ratio F` | `0.30` | 版框 bbox 面积最小比例 |
| `--trim-frame-max-fill F` | `0.15` | 版框空心判定上限 |

#### 4.9.4 手动裁切参数（v2.2+ / v2.3+）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--manual-odd-padding "T=50,B=40,I=80,O=30"` | None | 奇页 padding |
| `--manual-even-padding "T=50,B=40,I=80,O=30"` | None | 偶页 padding（v2.3+；不指定则从奇页镜像生成） |
| `--manual-mirror-even` | None | **v2.3+ 已废弃**；传值会被忽略并 warn |
| `--manual-preset PATH` | None | 从 JSON preset 加载 |
| `--manual-save-preset PATH` | None | 保存当前配置为 JSON |

#### 4.9.5 预处理参数（v1.9+）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--preprocess "sharpen,denoise=7,..."` | `""` | 预处理链（deskew 之前） |
| `--preprocess-quality {fast,balanced,best}` | `balanced` | 质量档 |

#### 4.9.6 二值化参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--binarize {none,otsu,adaptive,sauvola}` | `none` | 二值化算法 |
| `--binary-mode {1bit,8bit}` | `1bit` | 输出位深（环境变量 `BOOKCUT_BINARY_MODE` 可覆盖） |

#### 4.9.7 输出参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--format {png,jpg,jpeg,tif,tiff,webp}` | `png` | 输出图片格式 |
| `--pdf` | 关 | 同时输出合并 PDF |
| `--page-order {ltr,rtl}` | `ltr` | 1:2 切分时输出顺序 |
| `--no-outline` | 开 | 关闭 PDF outline / metadata 透传 |
| `--pdf-page-size {keep,max,first,a4,a5,letter,legal,kpw6,custom}` | `keep` | PDF 页面统一尺寸 |
| `--pdf-page-dim "WxH"` | None | 自定义尺寸（仅 custom） |
| `--pdf-page-unit {mm,cm,inch,px}` | `mm` | 自定义尺寸单位 |
| `--clean-output`（v2.3.5+） | **关** | 运行前 `rmtree(--output)`，**有数据丢失风险**——会清空整个 output_dir 再写新结果。dry-run 模式无效 |

#### 4.9.8 Dry-run 参数（v1.8+）

| 参数 | 默认 | 说明 |
|------|------|------|
| `--dry-run` | 关 | 预览模式（不写盘） |
| `--sample-n N` | `3` | 采样页数（最小 1） |
| `--preview-output DIR` | 系统 tmpdir | 预览输出目录 |

**v2.3.5+ 卫生清理**：每次新 dry-run 启动时，自动扫描 `tempfile.gettempdir()` 下的 `book-cut-preview-*` 目录，删除 **>7 天**的旧预览（best-effort，删不掉跳过）。无需 opt-in。旧版本残留的预览目录第一次跑新版本时自动清。

---

## 5. GUI 图形界面使用

### 5.1 启动

```bash
# 方式 1：从命令行启动
python -m book_cut --gui

# 方式 2：macOS .app 双击
open "dist/Book Cut.app"
```

启动后弹出主窗口（macOS 自动用 aqua 主题）。

### 5.2 界面布局

主窗口自上而下分 4 段：

```
┌────────────────────────────────────────────────────┐
│  [输入路径]              [浏览…]                   │  ← 段 1：输入
├────────────────────────────────────────────────────┤
│  [输出目录]              [浏览…]                   │  ← 段 1：输出
├────────────────────────────────────────────────────┤
│  切分策略:  [gutter ▼]   单页裁切: [trim ▼]       │  ← 段 2：处理
│  倾斜校正:  [☐]          二值化:   [sauvola ▼]    │
│  抗杂质:    [☐]          自适应:   [☑]             │
│  Trim 高级:  [展开 ▼]                              │
│  Manual Crop: [展开 ▼]   ← v2.2+ 折叠面板          │
│  图像增强:   [preset ▼] [balanced ▼]               │
│  Dry-run 预览:  [☐]  采样: [3]                    │
├────────────────────────────────────────────────────┤
│  输出格式: [png ▼]  [☐ 1-bit 紧凑]                │  ← 段 3：输出
│  页序:     [先左后右 ▼] [☐ 保留书签]              │
│  [☐ 输出 PDF]                                      │
│  PDF 页面尺寸: [keep ▼]  [W] [H] [mm]            │
├────────────────────────────────────────────────────┤
│  [开始处理]   [停止]                               │  ← 段 4：执行
│  [打开预览目录]   [打开输出目录]                   │
│  日志框：                                          │
│  ┌────────────────────────────────────────────┐   │
│  │ [INFO] manual crop: odd=... even=...       │   │
│  │ [INFO] 自适应裁切: paper = 180.0          │   │
│  │ ...                                         │   │
│  └────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
```

### 5.3 工作流：典型 5 步操作

**场景**：扫描了 130 页古籍 PDF（`尸子卷上下.pdf`），要切分成 260 张单页图 + 合并 PDF。

1. **选输入**：点"浏览…" → 选 `尸子卷上下.pdf`
2. **选输出**：点"浏览…" → 选（或新建）目录 `~/Desktop/尸子卷_切分`
3. **设置处理**：
   - 切分策略: `gutter`（默认）
   - 单页裁切: `trim`
   - 倾斜校正: ☑
   - 二值化: `sauvola`
   - 自适应: ☑
4. **设置输出**：
   - 输出格式: `png`
   - 1-bit 紧凑: ☑
   - 输出 PDF: ☑
   - PDF 页面尺寸: `a4`（统一 A4 打印友好）
5. **点"开始处理"** → 看日志输出进度 → 完成后自动打开输出目录

### 5.4 手动裁切拖框（v2.3 重点）

**场景**：古籍版框不规则 / 鱼尾密集 / 版心装饰复杂，auto trim 效果差。

#### 5.4.1 打开 Manual Crop 面板

在"处理"段找到 **Manual Crop: [展开 ▼]**，点击展开。

#### 5.4.2 拖奇页框

1. 点 **📐 拖奇页框** 按钮 → 弹出裁切窗口
2. 窗口里显示当前页的预览（支持缩放 / 适应窗口）
3. **按住鼠标左键** 在画布上拖一个矩形框住内容
4. 松开鼠标 → 自动反算 4 个 padding（T / B / I / O）并填入 Spinbox
5. 点 **应用** 关闭

#### 5.4.3 拖偶页框

重复以上步骤，但点 **📐 拖偶页框** 按钮。

#### 5.4.4 手动调整 Spinbox

也可以直接在 Spinbox 里微调 4 个 padding 数值（每个 ±1 px 步进）。

#### 5.4.5 保存 / 加载 preset

- **保存 preset**：点 **Save preset…** → 选保存路径 → 生成 JSON 文件
- **加载 preset**：点 **Load preset…** → 选 JSON 文件 → 自动填入两组 padding

#### 5.4.6 切换裁切模式

`--crop` 下拉选 `manual` 时，Manual Crop 面板才 enable；选 `none` / `trim` / `border` 时 disable。

### 5.5 停止与取消

**长跑作业时**（如 100+ 页 PDF）：

1. 点 **开始处理** 后，按钮置灰
2. **停止** 按钮 enable
3. 跑的过程中随时点 **停止** → 优雅取消（单页计算保持原子性，不写半截 PDF）
4. 取消后：已生成的图保留；PDF 不写
5. 再次点 **开始处理** 可重启

### 5.6 进度条（v2.3.3+）

进度条真实反映处理进度——不再是单纯的"沙漏动图"。

- **启动时**：自动用 `count_pages(input)` 轻量统计总页数（不渲染）
- **处理中**：进度条从 0% 填充到 100%，右侧 Label 实时显示 `X / Y 页 (Z%)`
- **完成**：进度条 100% + Label `✅ Y / Y`
- **停止**：Label `⏹ 已停止 (X / Y)`（X 为实际处理到的页数）
- **出错**：Label `❌ X / Y`
- **Dry-run 模式**：进度条退回 indeterminate（左右滑动）+ Label `(Dry-run)`（dry-run 不走全本）

---

## 6. 推荐配方（古籍场景）

### 6.1 配方速查表

| 场景 | 推荐命令 |
|------|----------|
| 漫漶无版框古籍 | `--deskew --split gutter --binarize sauvola --pdf` |
| 版面整齐的现代排印 | `--split gutter --crop trim --binarize sauvola --pdf` |
| 有版框的古籍 | `--deskew --split border --crop border --binarize sauvola --pdf` |
| 扫描件有倾斜 | 加 `--deskew` |
| 扫描件有噪点 | 加 `--preprocess "denoise=7"` |
| 泛黄纸 / 光照不均 | 加 `--preprocess "clahe=2.0"` |
| 深底封面 | 加 `--preprocess "gamma=0.7"` |
| 单页扫描（已是单页） | `--split none --crop trim` |
| 鱼尾密集 / 版心不规则 | `--crop manual`（GUI 拖框） |
| 繁体竖排古籍 | 加 `--page-order rtl` |
| 打印输出 | `--pdf --pdf-page-size a4` |

### 6.2 漫漶无版框古籍（最常用）

```bash
python -m book_cut -i 尸子卷上下.pdf -o ./out \
    --deskew \
    --split gutter \
    --binarize sauvola \
    --pdf
```

### 6.3 泛黄古籍 + 噪点 + 版心装饰

```bash
python -m book_cut -i 醉翁琴趣外篇.pdf -o ./out \
    --deskew \
    --split gutter \
    --crop trim \
    --preprocess "denoise=7,clahe=2.0,sharpen=1.5" \
    --binarize sauvola \
    --pdf \
    --pdf-page-size a4
```

### 6.4 鱼尾密集 / 版心不规则（手动裁切）

GUI 操作：
1. 选输入输出
2. 切分策略: `gutter`
3. 单页裁切: `manual`
4. 展开 Manual Crop 面板
5. 拖奇页框 + 拖偶页框
6. 输出 PDF: ☑
7. 开始处理

### 6.5 调参流程（先 dry-run 后正式跑）

```bash
# 步骤 1：dry-run 看 3 页效果
python -m book_cut -i book.pdf -o ./out \
    --split gutter --binarize sauvola \
    --dry-run --sample-n 3

# 步骤 2：查看 preview/preview_p0001_compare.png
#   看着不满意？换策略
python -m book_cut -i book.pdf -o ./out \
    --split border --binarize sauvola \
    --dry-run --sample-n 3

# 步骤 3：满意后跑全本
python -m book_cut -i book.pdf -o ./out \
    --split border --binarize sauvola --pdf
```

---

## 7. 常见问题 FAQ

### Q1：切分后左右页反了

古籍繁体竖排常用 `rtl`（先右后左）：

```bash
python -m book_cut -i book.pdf -o ./out --page-order rtl --split gutter
```

GUI 在"输出格式"段有"页序"下拉。

### Q2：trim 切过头了 / 切少了

**切多了（内容被切掉）**：

```bash
# 加大 adaptive padding
python -m book_cut ... --crop trim --adaptive-padding 50

# 关闭形态学（保留小字）
python -m book_cut ... --crop trim --no-morph
```

**切少了（白边还在）**：

```bash
# 设 0=完全贴 bbox（最紧）
python -m book_cut ... --crop trim --adaptive-padding 0
```

### Q3：找不到版框

切分时找不到版框会**自动回退到中缝**。要强制用版框：

```bash
python -m book_cut -i book.pdf -o ./out --split border
```

**注意**：用 `--split border` 而非 `--split gutter` 时，**必须**有清晰版框；否则可能切分失败。

### Q4：单页扫描件怎么切

```bash
# 已经是单页，不切分
python -m book_cut -i single_page.png -o ./out --split none --crop trim
```

如果单页扫描件有 book 的多页（如 `book.pdf` 每页已是单页），用同样命令即可。

### Q5：手动裁切 / auto trim 怎么选

| 场景 | 选哪个 |
|------|--------|
| 普通现代排印古籍 | auto trim（默认） |
| 版面整齐的 PDF | auto trim |
| 鱼尾密集 / 版心装饰复杂 | 手动裁切 |
| 版框残缺 / 扫描模糊 | 手动裁切 |
| 批量处理多本类似书 | 手动裁切 + preset 复用 |

### Q6：古籍奇偶页内容不对称怎么办

v2.3+ 奇偶页 padding **完全独立**：

```bash
python -m book_cut -i book.pdf -o ./out \
    --crop manual \
    --manual-odd-padding "T=50,B=40,I=80,O=30" \
    --manual-even-padding "T=50,B=40,I=30,O=80"
```

### Q7：输出 PDF 在阅读器里页大小不一致

```bash
python -m book_cut -i book.pdf -o ./out --split gutter --binarize sauvola \
    --pdf --pdf-page-size a4
```

可用 `keep` / `max` / `first` / `a4` / `a5` / `letter` / `legal` / `custom`。

### Q8：处理太慢

```bash
# 1) 用更快的预处理档
python -m book_cut -i book.pdf -o ./out --preprocess "..." --preprocess-quality fast

# 2) 跳过 deskew
python -m book_cut -i book.pdf -o ./out --split gutter  # 不要 --deskew

# 3) 用更简单的二值化
python -m book_cut -i book.pdf -o ./out --binarize otsu   # 比 sauvola 快

# 4) 跳过 trim
python -m book_cut -i book.pdf -o ./out --crop none --split gutter
```

### Q9：怎么保留原 PDF 的书签

默认保留。关闭：

```bash
python -m book_cut -i book.pdf -o ./out --pdf --no-outline
```

### Q10：怎么把同一配置用到多本书

用 preset：

```bash
# 1) 跑第一本时保存 preset
python -m book_cut -i book1.pdf -o ./out1 \
    --crop manual --manual-odd-padding "..." --manual-even-padding "..." \
    --manual-save-preset ./my_profile.json

# 2) 跑第二本时加载 preset
python -m book_cut -i book2.pdf -o ./out2 \
    --crop manual --manual-preset ./my_profile.json
```

---

## 8. 故障排查

### 8.1 安装问题

#### `pip install` 报错

**问题**：`error: Microsoft Visual C++ 14.0 or greater is required`（Windows）

**解决**：安装 [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 或改用 conda：

```bash
conda install -c conda-forge book-cut
```

#### OpenSSL 3.0 legacy provider crash

**症状**：启用 `--pdf` 时崩溃，报 `OpenSSL 3.0's legacy provider failed to load`

**解决**（v0.1.7+ 已自动修）：设环境变量 `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`

```bash
export CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1
```

或升级 cryptography：`pip install -U cryptography`

### 8.2 运行时问题

#### 找不到输入文件

**症状**：`FileNotFoundError: [Errno 2] No such file or directory: 'book.pdf'`

**排查**：
1. 路径是否含空格 / 中文 / 特殊字符？用引号包起来：`python -m book_cut -i "我的书.pdf"`
2. 相对路径时，确认 cwd 是项目根目录
3. PDF 大小写：`book.PDF` vs `book.pdf`（Linux 区分大小写）

#### 找不到输出目录的写权限

**症状**：`PermissionError: [Errno 13] Permission denied: '/usr/local/out'`

**解决**：
1. 输出目录改到有写权限的位置（如 `~/Desktop/out`）
2. Linux/macOS 用 `sudo` 不推荐，应改路径
3. Windows 不要输出到 `C:\Program Files\` 等系统目录

#### PDF 解析失败

**症状**：`PyMuPDF` 报错或 PDF 读不出来

**排查**：
1. PDF 是否加密 / 有密码？先用其他工具解密
2. PDF 是否损坏？用 `pdfinfo book.pdf` 或 Adobe Reader 打开试试
3. 把 PDF 转图片后再处理：`pdftoppm book.pdf scan -png -r 300` → `python -m book_cut -i ./scan-*.png ...`

#### 切分置信度低

**症状**：dry-run JSON 里 `pages[0].split.confidence < 0.5`，且预览图看着不对

**解决**：
1. 换切分策略：`gutter` → `border` 或反之
2. 加 `--deskew`（扫描倾斜时影响巨大）
3. 用 `--split none` + GUI 手动裁切
4. 减小 `--half-offset`（如果用了 `half`）

### 8.3 macOS Gatekeeper 拦截

**症状**：双击 `Book Cut.app` 没反应 / 提示"无法打开"

**解决**（任选一种）：

```bash
# 方式 1：移除 quarantine 属性
xattr -d com.apple.quarantine "dist/Book Cut.app"

# 方式 2：右键 → "打开" → "仍要打开"（首次后不再拦截）
```

详细打包文档见 [`docs/packaging.md`](packaging.md)。

### 8.4 性能问题

#### 内存爆

**症状**：`MemoryError` 或系统卡死

**原因**：高清扫描件（如 8000×10000）一次处理多页

**解决**：
1. 降低输入分辨率：`pdftoppm book.pdf scan -png -r 200`（默认 300 dpi 可降到 200）
2. 拆成多本小 PDF 分批处理
3. 用 `--preprocess-quality fast` 加速

#### 处理特别慢

**症状**：100 页跑 5+ 分钟

**排查**：
1. 用 dry-run 看 `elapsed_ms.per_page_avg`，定位哪步慢
2. 大头通常是：
   - `best` 档预处理（NL-Means ~850 ms / 页）→ 改 `fast` 或 `balanced`
   - Hough deskew → 用 `--no-deskew`（如果扫描不歪）
3. 见 [Q8](#q8处理太慢)

### 8.5 验证安装

跑测试套件（开发者）：

```bash
.venv/bin/pytest -v
# 应输出：434 passed
```

跑一个真实样本（端到端验证）：

```bash
python -m book_cut \
    -i samples/尸子卷上下.浙江书局.光绪三年刊.pdf \
    -o /tmp/test_out \
    --split gutter --binarize sauvola --pdf
ls /tmp/test_out/
# 应看到 *.png 和 *.pdf
```

---

## 9. 高级用法（Python API / 打包）

### 9.1 Python API

直接调用核心模块（CLI 暴露的子集）：

```python
from book_cut.io.loader import iter_pages
from book_cut.preprocess.deskew import deskew
from book_cut.preprocess.binarize import binarize
from book_cut.split.gutter import split_gutter
from book_cut.detect.trim import trim_margins

for page in iter_pages("book.pdf"):
    img = deskew(page.image)              # 倾斜校正
    left, right = split_gutter(img)        # 中缝切分
    left = trim_margins(left)              # 白边裁切
    left = binarize(left, "sauvola")       # 二值化
    left.save(f"{page.source_name}_L.png")
    right.save(f"{page.source_name}_R.png")
```

更多模块见 `src/book_cut/`：
- `io.loader` / `io.exporter` / `io.page_size`
- `preprocess.sharpen` / `denoise` / `clahe` / `gamma`
- `split.half` / `split.gutter` / `split.border`
- `detect.trim` / `detect.border` / `detect.manual` / `detect.paper`
- `pipeline.orchestrator`（顶层 `run_pipeline`）

### 9.2 macOS .app 打包

```bash
bash packaging/build_macos.sh
# 产物：dist/Book Cut.app（约 238 MB，arm64）
```

给 Intel Mac 用：在 Intel Mac 上重跑同一脚本。

详细文档见 [`docs/packaging.md`](packaging.md)。

### 9.3 Windows .exe 打包（待实现）

v2 路线图候选。当前可在 Windows 上：

```powershell
pyinstaller --noconfirm --clean "packaging/Book Cut.spec"
# 产物：dist/Book Cut/Book Cut.exe
```

### 9.4 开发工具链

```bash
# 跑全部测试（434 个）
.venv/bin/pytest

# 跑特定测试文件
.venv/bin/pytest tests/test_manual_crop.py -v

# 测试覆盖率
.venv/bin/pytest --cov=book_cut

# 静态检查
.venv/bin/ruff check src tests

# 自动修复（部分规则）
.venv/bin/ruff check --fix src tests

# 生成测试样本图
.venv/bin/python scripts/make_sample.py samples/sample_two_page.png
```

### 9.5 项目结构

```
src/book_cut/
├── cli.py                          # argparse 入口
├── gui.py                          # Tkinter GUI
├── gui_canvas.py                   # CropCanvas 拖框组件
├── pipeline/
│   ├── orchestrator.py             # 主循环
│   ├── dry_run.py                  # 预览模式
│   ├── preview.py                  # 对比拼图 + 指标 JSON
│   ├── crop_config.py              # 裁切配置解析
│   └── outline.py                  # PDF outline 注入
├── io/
│   ├── loader.py                   # PDF / 图片 / 文件夹加载
│   ├── exporter.py                 # 图片 / PDF 导出
│   └── page_size.py                # PDF 页面统一尺寸
├── split/
│   ├── half.py / gutter.py / border.py
├── detect/
│   ├── _utils.py                   # 共享 helper
│   ├── _hough.py                   # 共享 Hough
│   ├── trim.py                     # 白边裁切
│   ├── border.py                   # 版框内裁
│   ├── manual.py                   # 手动裁切（v2.2+）
│   ├── paper.py                    # 纸张色估计
│   └── single_page.py              # 单页检测
└── preprocess/
    ├── deskew.py                   # 倾斜校正
    ├── binarize.py                 # 二值化
    ├── sharpen.py / denoise.py / clahe.py / gamma.py
```

---

## 附录 A：版本历史摘要

| 版本 | 日期 | 关键变更 |
|------|------|----------|
| **v0.3.1** | 2026-06-25 | v2.3 独立奇偶页裁切（`ManualCropProfile` 重构 + 独立 odd/even padding + GUI 双拖框） |
| v0.3.0 | 2026-06-24 | v2.2 手动裁切工具（`--crop manual` + preset + GUI CropCanvas） |
| v0.2.0 | 2026-06-24 | v2.0 二值化 1-bit 紧凑输出（PNG/PDF 体积 ~30% 缩） |
| v0.1.12 | 2026-06-23 | v1.9 图片预处理增强（sharpen / denoise / clahe / gamma） |
| v0.1.11 | 2026-06-23 | v1.8.2 trim 鲁棒性补丁（稀疏墨迹 + 贴边保护） |
| v0.1.10 | 2026-06-23 | v1.8.1 GUI 停止按钮 |
| v0.1.9 | 2026-06-23 | v1.8 Dry-run 预览模式 |
| v0.1.8 | 2026-06-22 | v1.7 PDF 页面统一尺寸 |
| v0.1.7 | 2026-06-22 | OpenSSL 3.0 legacy provider 修复 |
| v0.1.6 | 2026-06-22 | v1.6 性能优化 + 抗伤字/抗杂质 |
| v0.1.5 | 2026-06-21 | v1.5 per-page paper + 流式 iter_pages |
| v0.1.4 | 2026-06-21 | v1.4 PDF outline / metadata 透传 |
| v0.1.3 | 2026-06-21 | v1.3 自适应裁切 |
| v0.1.2 | 2026-06-21 | v1.2 macOS .app 打包 |
| v0.1.1 | 2026-06-21 | v1.1 MVP（三种切分 + deskew + trim + binarize + PDF） |

## 附录 B：术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| 中缝 | gutter | 双页扫描件两页之间的缝隙 |
| 版框 | border / frame | 古籍页面周围的方框线 |
| 版心 | text block | 版框内的文字区域 |
| 鱼尾 | yúwěi / fish tail | 古籍版心中缝处的装饰图案 |
| 天 / 地 | top / bottom margin | 页面顶部 / 底部的留白 |
| 内 / 外 | inner / outer | 中缝侧 / 外侧 |
| 奇页 | odd / recto | 书的右页（中缝在左） |
| 偶页 | even / verso | 书的左页（中缝在右） |
| 漫漶 | màn huàn | 古籍因年代久远字迹模糊 |
| 倾斜校正 | deskew | 校正扫描件的旋转角度 |
| 自适应 | adaptive | 根据图像内容自动调整参数 |

---

**许可**：MIT · **作者**：yewei · **版本**：v0.3.1（v2.3 独立奇偶页裁切）
