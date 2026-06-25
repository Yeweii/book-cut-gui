# CHANGELOG

## [0.3.3] - 2026-06-25 · v2.3.3（GUI 真实进度条）

### Changed
- **进度条 indeterminate → determinate**（v2.3.3+）：原来的沙漏条只是动画，不反映实际进度。现显示 `已处理 / 总页（百分比）`：
  - 启动前 `count_pages(input)` 轻量统计总页数（只读 PDF metadata，不渲染）
  - 进度条 `mode="determinate"`，`maximum = total_pages`
  - 右侧 Label 实时显示 `X / Y (Z%)`
  - 完成：`✅ Y / Y`；停止：`⏹ 已停止 (X / Y)`；出错：`❌ X / Y`
- **dry-run 模式**：进度条退回 indeterminate + Label `(Dry-run)`（dry-run 不进 tqdm 循环，没真实页数）

### Added
- **`book_cut.io.loader.count_pages(source)`**：轻量页数统计，单 PDF / 单图 / 文件夹 / 嵌套都支持
- **`tests/test_loader_count_pages.py`**：7 个用例（单 PDF / 单图 / 文件夹混合 / 嵌套 / 不存在 / 不支持 / 空目录）

### Implementation
- **`gui._QueueWriter` 加 tqdm 正则**：`\r切分: 50%|...| 38/76 ...\r` 或 `\r切分: 76it ...\r` → 发 `("progress", pages_done)` 而不是 log
  - 不需要改 orchestrator 任何代码
  - 中间循环 "n/total" → pages_done = n + 1（+1 给 tqdm 循环外的 first_page）
  - 完成行 "Xit" → pages_done = X（initial + len = 总页数）
- **`total_pages_holder` + `last_progress_holder`**：on_run 填 / poll_queue 读，跨线程传递状态

### Tests
- 测试套件 **435 → 442**（+7），全过
- ruff 在修改文件 0 错
- tqdm 输出解析 smoke test：模拟 76 页输出 → progress 序列 [1, 11, 41, 76, 76] ✓

---

## [0.3.2] - 2026-06-25 · v2.3.3（PDF 页面尺寸：Kindle KPW6）

### Added
- **`--pdf-page-size kpw6`**（v2.3.3+）：Amazon Kindle Paperwhite 6（11 代，2021 年）原生页面尺寸
  - 6.8" E Ink Carta 1200 @ 300 ppi → display 1648×1232 px = **139.5 × 104.3 mm**
  - 96 DPI 换算 = (527, 394) px
  - 长宽比 4:3 = 1.3377（与设备 aspect ratio 一致）
  - 适合"扫描件 → 发 Kindle"工作流：CLI / GUI 都可用
- **GUI 联动**：`PDF 页面尺寸` combobox 新增 `KPW6 (6.8")` 项
- **测试** `test_pdf_page_size.py::test_t4b_parse_kpw6`：精确尺寸 + 长宽比双断言
- **`pipeline/orchestrator.py` 重构**：消除预设硬编码集 `{"a4","a5","letter","legal","custom"}`，改为从 `PDF_PAGE_SIZE_CHOICES` 动态派生（v2.3.3+ 未来加新 preset 只需改 `PRESETS` + `PDF_PAGE_SIZE_CHOICES` 两处，不再需要同步 orchestrator）

### Backward Compat
- 完全兼容 v2.3.x：旧 preset 名 / 老 PDF 配置文件不动
- 默认行为不变（`--pdf-page-size keep`）

### Tests
- `tests/test_pdf_page_size.py` +1 用例（T4b kpw6 尺寸）
- 测试套件 **434 → 435**（+1），全过，ruff 0 错（修改文件）
- 真实样本 smoke：76 页 sample PDF + `--pdf-page-size kpw6` → 152 张子页，mediabox 395.25×295.50 pt = 139.4×104.2 mm（与目标 ±0.1 mm）

---

## [0.3.1] - 2026-06-25 · v2.3（独立奇偶页裁切）

### Changed
- **`ManualCropProfile` 重构**：用 `odd_page` + `even_page` 两个 `PageCropProfile` 替代旧的 `mirror_even` 镜像
  - 实测古籍奇偶页常非物理对称（鱼尾形态、版心位置、版框残缺），镜像错位 → 独立裁切更准
  - `apply_manual_crop(arr, profile, is_even)` 简化为按 `is_even` 选 profile

### Added
- **JSON schema v2**：`{"odd_page": {...}, "even_page": {...}, "version": 2}`
- **新 `PageCropProfile` dataclass**：`top/bottom/inner/outer` 4 字段
- **CLI `--manual-even-padding "T,B,I,O"`**：偶页 padding 独立指定
- **GUI 双 Spinbox 组 + 双拖框按钮**："📐 拖奇页框" / "📐 拖偶页框"
- **新 preset 示例** `samples/crop_profiles/v2_独立奇偶示例_尸子卷.json`

### Deprecated
- **`--manual-mirror-even`**：v2.3+ 已废弃，传值时 warn 后忽略，请改用 `--manual-even-padding`

### Backward Compat
- `from_json` 自动迁移 v1 preset：
  - `mirror_even=True` → `even_page = {T,B,outer,inner}`（镜像）
  - `mirror_even=False` → `even_page = odd_page`（相同）
- 旧 JSON 文件不动；新 `to_json()` 始终输出 v2 格式

### Tests
- `tests/test_manual_crop.py` +6 个用例：独立裁切 / v1 mirror / v1 no-mirror / v2 round-trip / orchestrator 集成 / GUI Spinbox 隔离
- `tests/test_gui_manual_layout.py::test_apply_profile_to_vars` 改为按 `is_even` 选择 odd/even 写入
- 测试套件 **289 → 295**（+6 net），全过

---

## [0.3.0] - 2026-06-24 · v2.2（手动裁切工具）

### Added
- **`--crop manual` + 4 个 `--manual-*` 参数**：手动裁切工具，作为 auto 的兜底
  - `--manual-odd-padding "T=50,B=40,I=80,O=30"` 或 `"50,40,80,30"`（顺序 T,B,I,O）
  - `--manual-mirror-even`（默认 True，偶页自动 inner↔outer 镜像）
  - `--manual-preset PATH`：从 JSON 加载 profile
  - `--manual-save-preset PATH`：运行时保存为 JSON
- **新模块 `book_cut.detect.manual`**（v2.2+）：
  - `ManualCropProfile` dataclass（top/bottom/inner/outer + mirror_even + source_size + notes）
  - `apply_manual_crop(arr, profile, is_even)`：按 profile 切出子图
  - `parse_manual_padding(s)`：CLI 字符串 → 4 个 int
  - `canvas_to_image` / `padding_from_rect`：拖框数学（纯函数，单测可独立验证）
- **新模块 `book_cut.gui_canvas`**：`CropCanvas` 类（拖框 Canvas，鼠标交互 + 实时反算 padding）
- **GUI "Manual Crop" 折叠面板**（crop_var=="manual" 时启用）：
  - 4 个 Spinbox（Top/Bottom/Inner/Outer）+ Mirror checkbox
  - "Load preset…" / "Save preset…" 按钮
  - 与 `--crop manual` 联动
- **preset 示例** `samples/crop_profiles/尸子卷_浙江书局_光绪三年刊.json`（嵌套 schema）
- **JSON schema 两种格式**：
  - 简洁：`{"top":50, "bottom":40, "inner":80, "outer":30, ...}`
  - 嵌套：`{"odd_page": {"top":50, ...}, "mirror_even":true, "name":"...", ...}`

### Changed
- **orchestrator 新增 `crop_mode=="manual"` 分支**：manual profile 完全替代 auto crop
- **CLI `--crop` choices** 加 `manual`
- **行数预算**：orchestrator 850→900、pipeline 1540→1610（manual 模块 +233 在 detect 目录）

### 与 v2.1 trim-ab 的关系
互补：v2.1 增强 auto 算法（A+B）；v2.2 提供 manual 兜底工具
- 疑难古籍（鱼尾密集、版框异形）→ manual 接管
- 普通古籍 → auto 继续

## [0.2.0] - 2026-06-24 · v2.0

### Added
- **`binary_mode` 选项** (`preprocess/binarize.py`)：二值化输出位深选择
  - `1bit`（默认）：1-bit 调色板（值 0/1），PNG/PDF 体积缩到 8-bit 输出的 ~70%
  - `8bit`：旧 v1.9 行为，向后兼容
- **CLI** `--binary-mode {1bit,8bit}`：默认 1bit
- **环境变量** `BOOKCUT_BINARY_MODE`：覆盖 CLI 默认
- **GUI** "1-bit 紧凑输出"checkbox：默认勾选

### Changed
- **`binarize_otsu/adaptive/sauvola` 加 `binary_mode` 参数**（默认 `"1bit"`）
- **`_to_1bit_image` 新增**：走 `L → 1` + `dither=NONE`（PIL `Image.fromarray(bool_arr, mode="1")` 不支持 bool 数组，会返回全黑）
- **`binarize` dispatcher 透传 `**kwargs`**：以前只对 `adaptive` 和 `sauvola` 透传；现在统一透传 `binary_mode`
- **`_compute_page` + `run_dry_run` 加 `binary_mode` 字段**：从 `args` 读默认值

### Performance（实测 6400×8534 尸子图 split=none）
| 模式 | PDF 体积 | 缩减 |
|------|----------|------|
| v1.9.2（8-bit L + Flate） | 651 KB | 1.00x |
| v2.0（1-bit + Flate） | 459 KB | **1.42x** |

注：理论 1-bit raw 字节是 8-bit 的 1/8（8x），但真实古籍二值化后熵较高
（边缘飞白、噪点），Flate 压缩后实际缩减 1.4-1.6x。要进一步缩减需 CCITT G4
（v2.1 候选）。

### Tests
- `tests/test_binarize.py` +9 个用例：3 算法默认 1-bit、explicit 8-bit 兼容、1-bit/8-bit 像素值等价、PNG 落盘体积缩减、none 模式 passthrough
- `tests/test_b3_sauvola_inplace.py` 8 个测试 opt-in `binary_mode="8bit"`（保持 B3 算法数值校验不受影响）
- 测试套件 **283 → 289**（+9 净），全过，ruff 0 错

### Docs
- `docs/dev/2026-06-24-v2.0-binary-1bit.md`：提案
- README：binarize 段加 `--binary-mode` 说明

---

## [0.1.12] - 2026-06-23 · v1.9

### Added
- **图片预处理增强** (`preprocess/{sharpen,denoise,clahe,gamma}.py`)：deskew 之前应用信号级增强
  - `sharpen`：Unsharp Mask（fast=PIL.SHARPEN / balanced+best=cv2 addWeighted）
  - `denoise`：fast=PIL GaussianBlur / balanced=cv2.bilateralFilter (d=9, σ=75) / best=cv2.fastNlMeansDenoising (NL-Means 全搜索)
  - `clahe`：cv2.createCLAHE 局部直方图均衡（fast 档 no-op）
  - `gamma`：伽马校正（γ<1 提亮，γ>1 压暗；clamp [0.25, 4.0]）
- **CLI** `--preprocess "sharpen,denoise=7,clahe=2.0,gamma=1.2"`：链语法 + `=value` 覆盖默认
- **CLI** `--preprocess-quality {fast,balanced,best}`：3 档后端选择
- **环境变量** `BOOKCUT_PREPROCESS_QUALITY`：覆盖默认 quality
- **GUI** "图像增强"控件：preset combobox（7 种 + custom）+ 质量 combobox + 自定义链 entry
- **dry-run 集成**：`--dry-run --preprocess ...` 自动出 4 联对比图（原始 | preprocess | deskew | binarize）
- **`preprocess` dispatcher** (`preprocess/__init__.py`)：链式应用 + 错误处理

### Changed
- **流水线顺序**：`load → preprocess → deskew → split → crop → binarize → export`（v1.9+ 加 preprocess）
- **A1 单次 RGB→L 保持不变**：preprocess 在 PIL.Image 上做，不破坏 arr 路径
- **`_compute_page` 返回 `raw_original`**：让 dry-run 区分"真·原始 vs preprocess 后"
- **`render_compare` 加 `preprocessed` 参数**：可选插入第 1 列（"PREPROCESS"）

### Performance（4000×4000 灰度全 4 op 链）
| 档位 | 耗时 | 算法核心 |
|------|------|----------|
| `fast` | ~110ms | PIL 内置 |
| `balanced` | ~180ms | cv2 bilateralFilter（**默认**，边缘保留 + 快） |
| `best` | ~850ms | cv2 fastNlMeansDenoising 全搜索 |

### Tests
- `tests/test_preprocess.py` 27 个用例：每档 3 op × 3 quality / 链顺序 / 参数解析 / 错误路径 / 集成 metrics
- 测试套件 **246 → 273**（+27），全过，ruff 0 错（修改文件）

### Docs
- README：新增"图片预处理增强（v1.9+）"章节（CLI 语法 / 性能表 / 推荐顺序）
- CLI 顶部可选处理列表加 preprocess 描述
- 流水线图加 preprocess 节点

---

## [0.1.11] - 2026-06-23 · v1.8.2

### Fixed
- **trim 贴边保护二级 fallback** (`detect/trim.py`)：v1.6+ 严格 safety (5-40px) 对版框线贴边的扫描页直接跳过裁切。v1.8.2+ 新增 `relaxed_safety = max(2, h*0.005)` 兜底；严格 hit 时放宽一次，多数古籍扫描的版框线可正常裁切
- **trim 稀疏墨迹保护** (`detect/trim.py _clean_ink_mask`)：实测发现 5% 密度稀疏墨迹走 `cv2.MORPH_OPEN(3×3)` 会全部清光（3×3 erode 杀孤立点）→ trim 找不到内容边界 → 输出原图。修复：墨迹密度 < 0.5% 跳过 morph

### Tests
- `tests/test_split_crop_robustness.py` +2 用例：T7b safety 二级 fallback 命中版框线 / T7c 稀疏墨迹保护
- 测试套件 **244 → 246**，全过
- 真实样本 smoke：ZHSY100456 + paper_pages=5（默认）+ trim + sauvola → 132 图 / 2.44 MB（与 v1.8.1 等价 —— 用户样本的 paper 偏黄导致 ink_thr 偏高，本改进对白纸 PDF/版框线场景收益明显）

### Note
- v1.8.2 是 v1.8.1 的 trim 鲁棒性补丁，不改变 CLI / GUI 行为
- 实测 PNG `optimize=True` 慢 42%（5.5s vs 3.85s）仅省 15% 体积，不采用；`compress_level=8` 慢 30% 省 8%，不采用；保持 PIL 默认（level 6）

---

## [0.1.10] - 2026-06-23 · v1.8.1

### Added
- **GUI 停止按钮**：长跑时可随时取消 —— `stop_btn` 紧邻 `run_btn`，按下后置灰防重按；后端线程池 cancel 事件透传
- **后端 `cancel_event`**：`run_pipeline(args, cancel_event=...)` 新增可选参数；`dry_run.run_dry_run` 也支持；单页计算保持原子性（边界检查，cancel 后不写 PDF）

### Tests
- `tests/test_stop.py`（4 个用例）：主循环 cancel / 不取消 / dry-run cancel / first_page 前 cancel
- 测试套件 **233 → 244**（+11 net：4 stop + 7 来自前序会话）
- 全 suite 过（1.89s stop 子集 / 13.44s 全量），无回归
- 真实样本 smoke：ZHSY100456 + 1.0s 取消 → 19 页边界停止 + 38 张图 + PDF 不写

### Note
- v1.8.1 是 v1.8 的小补丁（仅 GUI 增量 + cancel 透传），不改变 CLI / 流水线行为

---

## [0.1.9] - 2026-06-23 · v1.8

### Added
- **Dry-Run 预览模式** `--dry-run`：调参神器 —— 不写实际输出，仅跑前 N 页（默认 3）出对比拼图 + 指标 JSON
  - `--sample-n N`（默认 3）：采样页数
  - `--preview-output DIR`：预览输出目录（默认系统 tmpdir 带时间戳）
- **对比拼图**（`pipeline/preview.py`）：3 列（原图 | L | R）并排 + 红色虚线标记 split column + 等高对齐 + 总宽 ≤ 6000px
- **指标 JSON**（`preview_summary.json`）：包含 total_pages / sampled_pages / sample_indices / config / elapsed_ms / paper_color_estimate / pages 数组（每页 split confidence / crop boxes / binarize params / timings_ms / warnings）+ 自动调参建议
- **split confidence 量化**（`_compute_split_confidence`）：gutter 偏离中心 > 20% → 0；border 子图太小 → 0.3；half → 1.0
- 与 `--pdf` / `--format` / `--pdf-page-size` / `--no-outline` 写盘 flag 互斥（warn 后忽略）
- GUI 联动：勾选 Dry-run → 整张"输出格式"行 disable + 采样页 spinner enable；执行后 → "打开预览目录" 按钮 enable

### Refactor
- **C3 续**：`orchestrator.py` 抽出 `_compute_page`（纯计算）+ `_save_subpages`（写盘），dry-run 主体迁到 `pipeline/dry_run.py`（142 行）
- 新模块：`pipeline/preview.py`（272 行）— `render_compare` / `write_preview` / `compute_summary`

### Tests
- 测试套件 **228 → 233**（+5 net：dry-run 5 个核心 + C3 阈值更新）
- 全 suite 过，无回归
- 真实样本 smoke：ZHSY100456 + 茶山集各 1 次，对比图人眼检查通过

### Note
- `pipeline/orchestrator.py` 行数阈值 C3 从 400 提到 600（v1.8 加了 dry-run dispatch + `_compute_page` 抽出约 +140 行；dry-run 主体 142 行在 dry_run.py）
- `pipeline/` 包总行数阈值从 700 提到 1300（新增 dry_run.py + preview.py）

---

## [0.1.8] - 2026-06-22 · v1.7

### Added
- **PDF 页面统一尺寸 `--pdf-page-size`**：古籍扫描件合并 PDF 时所有页 page size 一致，避免"封面 3708×3862 / 文本 3424×3330 / 插图页 4288×3330"在 PDF 阅读器里大小跳变
  - `keep`（默认）= 保持 v1.6 行为（零侵入）
  - `max` = 所有输入页 `max(W) × max(H)`（流式预扫，PDF 133 页 < 100ms）
  - `first` = 首页尺寸
  - `a4` / `a5` / `letter` / `legal` = 标准预设（96 DPI）
  - `custom` = 自定义（`--pdf-page-dim WxH` + `--pdf-page-unit mm/cm/inch/px`）
- 图片 fit 策略：等比 fit + 居中 paste + 留白填 255（白）；mode 跟随子图（L / RGB）
- 仅 `--pdf` 模式生效；非 PDF 模式 → 警告后忽略（图片输出保持原分辨率）
- GUI 联动：combobox 选 `custom` → W/H/unit 三个输入框 enable；PDF checkbox 关闭 → 整行 disable

### Tests
- 测试套件 **213 → 228**（+15）
- 8 解析 + 4 fit + 2 实际 PDF mediabox（a4=595.5×842.25 pt / max=600×525 pt）+ 1 choice 校验
- 213 老测试零回归

### Note
- `pipeline/orchestrator.py` 行数阈值 C3 从 350 提到 400（v1.7 加了 max/first 预扫 + fit 步骤约 +50 行）

---

## [0.1.7] - 2026-06-22 · bug fix

### Fixed
- **OpenSSL 3.0 legacy provider crash**：在 macOS 启用 PDF 输出（`--pdf`）时，`pypdf` 内部 import `cryptography`，触发 `OpenSSL 3.0's legacy provider failed to load` fatal error（Homebrew `openssl@3` 把 legacy provider 拆为独立 formula，未装时即触发）。修复：`book_cut/__init__.py` 顶部 `os.environ.setdefault("CRYPTOGRAPHY_OPENSSL_NO_LEGACY", "1")`，确保在 cryptography 加载前生效。`setdefault` 不覆盖用户已设值。

### Tests
- 213 测试全过，无回归
- outline 注入链路（pypdf → cryptography）4 个 PDF fixture 实测可正常 read

---

## [0.1.6] - 2026-06-22 · v1.6

### Performance
- **B3**：Sauvola `sqrt(var)` 原地写，省 2 个 float32 临时（**17% 时间 ↓ / 28% 内存 ↓**）
- **A3**：`--split border --crop border` 时 Hough 一次算两个用途（split 外框 + 每页内框），**1.86× 加速**
- **A4**：`_resolve_outline_source` 单 PDF 路径消除冗余 IO
- **A5**：deskew projection 降分辨率（4000² → 1000²），**9.3× 加速**

### Refactor
- **C3**：`pipeline.py` (455 行) 拆 3 模块 `pipeline/{orchestrator,outline,crop_config}.py`，单文件最大值 455 → 306
- **C2**：`paper.py` / `trim.py` 重复公式合并到 `detect/_utils.py`（`to_gray_array` / `to_L_image` / `adaptive_padding`）
- **C1**：共享 `detect/_hough.py`（deskew / split_border / crop_border 复用 Hough）

### Robustness (v1.6 主线)
- 抗伤字：split border 找不到合适切线时回退到中缝
- 抗杂质：形态学开运算先清尘点（`--no-morph` 可关闭）

### GUI UX
- **E1a**：crop=none 时抗杂质 checkbox 自动禁用
- **E1b**：input 路径变化 + output 为空 → 自动建议 `{stem}_out` / `{name}_out`
- **E3**：FileNotFoundError / PermissionError / IsADirectoryError / NotADirectoryError → 中文友好提示

### Tests
- 测试套件 **199 → 213**（+14 net）
- 全 suite 过，无回归

---

## [0.1.5] - 2026-06-21 · v1.5

### Added
- **per-page paper color override**：单张子图 paper 偏离书级 ≥ `--paper-deviation` (默认 30) → 单独估 paper color，仅换 paper_color，保持 padding/ink_offset
- **流式 `iter_pages`**：B1 主循环迭代 generator，内存从 O(N×page) → O(page)
- **`inject_outline_and_metadata` 全内存**：B2 去掉 tempfile，img2pdf bytes → pypdf → 直接覆盖

### Performance
- Hough threshold 调优（SPLIT/CROP 双 preset）

---

## [0.1.4] - 2026-06-21 · v1.4

### Added
- **PDF outline / metadata 透传**：原 PDF 书签 + 元数据保留到输出 PDF（img2pdf 出无 outline 中间 PDF → pypdf 后处理注入）
- `--page-order {ltr,rtl}`：1:2 切分时输出顺序（古籍竖排常用 rtl）
- `--no-outline`：关闭 outline 透传（兜底）
- GUI 页序下拉 + 保留书签 checkbox（默认勾选）

### Dependencies
- 新增 `pypdf>=4.0`（outline 注入）

---

## [0.1.3] - 2026-06-21 · v1.3

### Added
- **自适应裁切**：`--crop-adaptive auto` 默认开启，前 N 页估 book paper color → 自适应墨迹阈值（`paper_color − 30`，下限 60）
- 自适应 padding = `max(短边 × 2%, 5)`，clamp ≤ 30
- 边缘"有内容"判定 ≥ 3 个 ink 像素（抗 JPEG 噪声）
- GUI 在"单页裁切"行多了 **自适应（按纸色）** 复选框 + **采样页** spinner

### Performance
- 古籍泛黄纸（paper median 200-220）裁切更紧致：ZHSY100456 平均尺寸 515×790 → 469×688

---

## [0.1.2] - 2026-06-21 · v1.2

### Added
- **macOS `.app` 打包**：`packaging/build_macos.sh` 一键 PyInstaller → `dist/Book Cut.app` (~220MB)
- `packaging/launch_gui.py` 绕过 CLI argparse，`.app` 双击 = GUI 启动

---

## [0.1.1] - 2026-06-21 · v1.1

### Added
- 三种切分策略：`gutter` / `border` / `half`
- 倾斜校正 `--deskew`（Hough 默认，fallback 投影）
- 单页裁切 `--crop {none,trim,border}`
- 二值化 `--binarize {none,otsu,adaptive,sauvola}`（Sauvola 适合古籍泛黄）
- 合并 PDF（img2pdf 无损）