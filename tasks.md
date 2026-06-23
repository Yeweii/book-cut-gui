# 任务分解

按依赖顺序排列。✅ = 已完成。

## Phase 0 · 项目骨架 ✅

- [x] 初始化 `pyproject.toml` / `requirements.txt`
- [x] 创建 `src/book_cut/` 目录骨架与 `__init__.py`
- [x] 配置 `ruff` + `pytest`

## Phase 1 · 输入加载 (`io/loader.py`) ✅

- [x] 实现 `iter_pages(source)` 统一接口
- [x] PDF 加载（pymupdf，300 DPI）
- [x] 单图加载（PIL）
- [x] 嵌套文件夹递归加载（rglob + 扩展名白名单 + 排序）
- [x] `tests/test_loader.py`

## Phase 2 · 最小切分闭环 ✅

- [x] `split/half.py`（对半切 + offset）
- [x] `split/gutter.py`（列投影找最白连续段）
- [x] `split/border.py`（Hough 找版框中心）
- [x] `pipeline.py` 串联 loader + split + exporter
- [x] `io/exporter.py`（图片 + 合并 PDF）
- [x] CLI 完整参数
- [x] `tests/test_split.py`

## Phase 3 · 版框检测 / 切白边 ✅

- [x] `detect/trim.py`（白边裁切 + padding）
- [x] `detect/border.py`（Hough 找内外框，裁到内框；找不到时回退 trim）
- [x] `tests/test_detect.py`

## Phase 4 · 二值化 ✅

- [x] `preprocess/binarize.py`（Otsu / Adaptive / Sauvola）
- [x] CLI `--binarize`
- [x] `tests/test_binarize.py`

## Phase 5 · 倾斜校正 ✅

- [x] `preprocess/deskew.py`（Hough + 投影；auto 回退）
- [x] CLI `--deskew`
- [x] 流水线位置：split 之前
- [x] `tests/test_deskew.py`

## Phase 6 · PDF 输出 ✅

- [x] `io/exporter.py` 的 PDF 合并（img2pdf 无损）
- [x] CLI `--pdf`

## Phase 7 · GUI ✅

- [x] Tkinter 单窗口（输入/输出/deskew/策略/裁切/二值化/格式/PDF/进度/日志）
- [x] 路径浏览 + 执行
- [x] 后台线程 + queue 日志推送
- [x] 进度条
- [x] `tests/test_gui.py`

## Phase 8 · 收尾 ✅

- [x] README 增补（完整用法 + 配方 + 项目结构）
- [x] CLI `--help` 完善
- [x] 端到端测试（33 测试 + 全链路 E2E）
- [x] `requirements.txt` 锁定版本（含间接依赖）
- [x] `archive` skill 写 Session Note

## 未来（不在 v1）

- 真实古籍扫描件校准 ✅ (v1.1)
- 自动 OCR 识别书名
- 倾斜方向自适应
- 切分质量评估
- Deep learning 版框检测

## v1.2 · macOS GUI 打包 ✅

- [x] PyInstaller 选型 + arm64 目标
- [x] `packaging/launch_gui.py`（GUI 入口，绕开 CLI）
- [x] `packaging/Book Cut.spec`（规格：collect tkinter、exclude matplotlib）
- [x] `packaging/build_macos.sh`（一键脚本）
- [x] 产物：`dist/Book Cut.app` 222MB arm64，启动正常
- [x] README 加打包章节
- [x] `docs/sessions/2026-06-21-book-cut-v1.2.md`

## v1.1 · 真实扫描件校准 ✅

- [x] PDF 全量（133 页）端到端跑通：21s / 266 张 / 26MB PDF
- [x] 文本页质量优秀（中缝准、Sauvola 锐、版框裁切干净）
- [x] 单页检测：白底单边墨迹可识别；深底封面（校色卡）当前识别不到
- [x] `--no-single-page` CLI 开关
- [x] 36 测试全过（原 33 + 单页 3）
- [x] `docs/sessions/2026-06-21-book-cut-v1.1.md` 校准记录

## v1.3 · 自适应裁切 ✅（在 v1.3-adaptive-crop 分支）

- [x] `detect/paper.py`：`CropConfig` + `estimate_paper_color`（95th p95，clip [180,255]）+ `aggregate_paper_color`（median）+ `adaptive_padding`（max(min*0.02, 5)，clamp 30）
- [x] `trim_margins` 加 `config=` kwarg；`config is None` 走 v1.1 legacy 路径（零行为回退）
- [x] `crop_to_border` 加 `config=` kwarg；3 处 trim fallback 全部传透 config
- [x] `pipeline._build_crop_config` 采样前 N 页估书级 paper color
- [x] CLI：`--crop-adaptive {auto,fixed}`（default auto）+ `--paper-pages N`（default 5）
- [x] GUI：自适应 checkbox（默认 on）+ 采样页 spinner（off 时 disabled）
- [x] 12 个新 test：paper color 估计器、aggregation、adaptive padding、adaptive vs fixed 回归钉子、yellowed paper 价值证明、border fallback 透传
- [x] 48 测试全过、ruff 0 错
- [x] ZHSY 验证：book paper color=218，132 图，对比 v1.1 文本页 -13%~-17% 紧致（正确：泛黄纸不再被当内容）
- [x] 茶山集 68 页回归：136 图 + PDF，行为一致
- [x] `docs/sessions/2026-06-21-book-cut-v1.3.md` v1.3 记录

## v1.3 · macOS GUI 打包 + 打包说明文档化 ✅

- [x] `packaging/Book Cut.spec` hiddenimports 加 `book_cut.detect.paper` + Info.plist 版本 0.1.2 → 0.1.3
- [x] `bash packaging/build_macos.sh` 跑通：`dist/Book Cut.app` 222MB arm64
- [x] 启动 smoke test：进程存活 5+ 秒无崩溃
- [x] PYZ 归档核查：`book_cut.detect.paper` 进了 bundle
- [x] 清理 samples/out_* 5 个临时输出目录
- [x] `docs/packaging.md` 新建：TL;DR / 前置 / 一键+手动 / 产物结构 / 发布版本 / 验证 5 步 / 常见问题 / Universal
- [x] `README.md` 打包段链接更新到 `docs/packaging.md`
- [x] `docs/sessions/2026-06-21-book-cut-v1.3-packaging.md` 打包记录

## v1.4 · PDF outline + metadata 透传 ✅（v1.4-outline-preserve 分支，未合 master）

- [x] 提案：`docs/dev/2026-06-21-v1.4-outline-preserve.md`（方案 D：pypdf 后处理）
- [x] 新增依赖 `pypdf==6.13.3`（纯 Python，~1MB，零间接依赖）
- [x] `io/loader.py` 新增 `get_pdf_outline` / `get_pdf_metadata` / `first_pdf_in_folder`（不污染 PageInfo 抽象）
- [x] `io/exporter.py` 新增 `inject_outline_and_metadata`（src → dst，pypdf 后处理）+ `STANDARD_METADATA_KEYS` 集合
- [x] `pipeline.py` 维护 `mapping: dict[orig_idx → list[out_idx]]`；1:2 时 `mapping[i][0]`；RTL 翻转 sub_pages；多 PDF 源警告
- [x] `cli.py` 新增 `--page-order {ltr,rtl}` + `--no-outline`（同时关 metadata）
- [x] `gui.py` 镜像：页序下拉 + 保留书签 checkbox
- [x] `Book Cut.spec` hiddenimports 加 `pypdf` + Info.plist 版本 0.1.3 → 0.1.4
- [x] `tests/conftest.py` 3 个 PDF fixture：with_outline / no_outline / nested_outline
- [x] `tests/test_outline.py` 17 个新 test（覆盖 T1-T11 + 3 个 helper + 3 个 E2E 场景）
- [x] 65 测试全过（原 48 + 新增 17）；ruff 0 错
- [x] ZHSY 验证：66 页 + 10 节点 outline 注入 → 132 输出页，outline 树完整保留，metadata 透传
- [x] 茶山集回归：133 页 + 12 节点 → 266 页，nested outline 完整
- [x] RTL 验证：--page-order rtl 翻转 [左,右]→[右,左]，outline 页号不变（"只指第一张"）
- [x] README 加 v1.4 段 + CLI 表 + 推荐配方
- [x] 记录：`docs/sessions/2026-06-21-book-cut-v1.4.md`

## v1.9 · 图片预处理增强（提案：2026-06-23）

> 提案：`docs/dev/2026-06-23-v1.9-preprocess-enhance.md`
> 续 v1.8 dry-run；本节先列任务，实施时按勾选推进。

### Phase A · D1 性能基准（先立）

- [ ] 跑 `tests/test_perf.py` 量化 v1.8 baseline（4000×4000 全链 + 单页耗时）
- [ ] 记录到 memory：v1.8 baseline ~160ms/页、各项分布

### Phase B · 4 个新模块

- [ ] `preprocess/sharpen.py`（PIL SHARPEN + cv2 unsharp mask，amount/radius 参数）
- [ ] `preprocess/denoise.py`（PIL GaussianBlur + cv2.fastNlMeansDenoising，h 参数）
- [ ] `preprocess/clahe.py`（cv2.createCLAHE，clip 参数）
- [ ] `preprocess/gamma.py`（numpy power LUT，value 参数，clamp [0.25, 4.0]）
- [ ] 4 个模块各自 `*_chain_token` 解析器（支持 `=value` 语法）
- [ ] `preprocess/__init__.py` 加 `preprocess(image, chain, quality)` dispatcher
- [ ] `BOOKCUT_PREPROCESS_QUALITY` 环境变量支持（fast/balanced/best，默认 balanced）

### Phase C · CLI

- [ ] `--preprocess` flag（链语法：逗号分隔 + `=value` 参数）
- [ ] `--preprocess-quality` flag（fast/balanced/best）
- [ ] CLI 校验：chain 空 / 非法 token / gamma 值越界
- [ ] `cli.py` 加 help 文本（与现有 flag 风格一致）

### Phase D · 流水线集成

- [ ] `pipeline/orchestrator.py:_compute_page` 在 deskew 之前插入 `preprocess(image, chain)`
- [ ] `run_pipeline` 读 `--preprocess` + `--preprocess-quality` 传给 `_compute_page`
- [ ] A1 单次 RGB→L 优化保持不变（preprocess 在 PIL 上做，不进 arr 路径）
- [ ] metrics 记录 preprocess 耗时（`page_metrics["timings_ms"]["preprocess"]`）

### Phase E · GUI（同步）

- [ ] row 5.5 "图像增强" frame：preset combobox + quality combobox + custom entry
- [ ] preset 列表：`none` / `sharpen` / `denoise` / `clahe` / `sharpen,denoise` / `denoise,clahe,sharpen` / `gamma,sharpen` / `custom`
- [ ] custom 模式：custom_entry enable，否则 disable
- [ ] quality combobox 默认 balanced
- [ ] `_on_preset_change` / `_on_pdf_change` 同步逻辑（pdf 关闭时仍可启用）
- [ ] 拼到 cmd_args 的 `--preprocess` + `--preprocess-quality`

### Phase F · dry-run 集成

- [ ] `--dry-run --preprocess ...` 自动出 4 联对比图：`[原始 RGB] | [preprocess 后] | [deskew 后] | [最终 binarize 后]`
- [ ] fast 模式不加第 2 列（避免依赖 cv2）
- [ ] 复用 `pipeline/dry_run.py` 现有拼图基础设施

### Phase G · 测试

- [ ] `tests/test_preprocess.py` 4 模块各 3-5 个 test（共 ~20 个）：
  - fast/balanced/best 各档位产出一致
  - 参数解析（`sharpen=2.0` / `gamma=1.3`）
  - 空链 / 非法 token / 越界 gamma 错误路径
  - 质量档环境变量覆盖
- [ ] 回归：228 测试零修改通过
- [ ] ruff 0 错

### Phase H · 真实数据验证

- [ ] ZHSY 132 图：`--preprocess "denoise,clahe,sharpen"` 对比 v1.8 baseline
- [ ] 茶山集 136 图回归
- [ ] 性能：fast < 30ms/页 / balanced < 100ms/页 / best < 200ms/页
- [ ] dry-run 4 联对比图人工确认增强有效

### Phase I · 文档 + 收尾

- [ ] README 加 v1.9 段：CLI 语法 + 推荐配方 + 质量档说明
- [ ] CHANGELOG 加 v1.9 条目
- [ ] 提案里的"待拍板"4 项决议落到代码注释 / README
- [ ] 写 `docs/sessions/2026-06-23-book-cut-v1.9.md` session note
- [ ] 更新 memory：`project_book_cut.md` v1.9 状态 + 踩坑

### 依赖关系

```
Phase A (D1 baseline)
   ↓
Phase B (模块)
   ↓
Phase C (CLI) ──┐
                ├→ Phase D (流水线)
Phase E (GUI) ──┘        ↓
                         ↓
                    Phase F (dry-run)
                         ↓
                    Phase G (测试)
                         ↓
                    Phase H (真实数据)
                         ↓
                    Phase I (文档)
```

### 工作量预估

- Phase A：0.5h（已有 test_perf.py）
- Phase B：2-3h（4 模块 + dispatcher）
- Phase C：0.5h（CLI flag）
- Phase D：1h（流水线 + metrics）
- Phase E：1h（GUI row）
- Phase F：1h（4 联图）
- Phase G：1.5h（~20 test）
- Phase H：1h（ZHSY + 茶山集）
- Phase I：1h（README + CHANGELOG + session note）

**总计 ~9-10h（1-2 天）**

### 不做（v2.0 候选）

- per-page preprocess override（与 v1.5 paper deviation 同思路）
- `--preprocess-after-crop`（binarize 之前的 per-page 增强）
- 自适应 preprocess（自动判断页面需要哪种增强）
