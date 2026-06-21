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
