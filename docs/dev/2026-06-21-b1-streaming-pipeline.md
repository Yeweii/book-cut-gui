# 2026-06-21 · v1.5 B1 流式 Pipeline（不积压 PageInfo）

## 0. 背景

v1.4 `pipeline.run_pipeline`（`src/book_cut/pipeline.py:165`）：

```python
pages: list[PageInfo] = list(iter_pages(args.input))  # ← 全量加载到 RAM
```

### 问题规模

| 场景 | 单页 RGB | 总内存 |
|---|---|---|
| 100 页古籍（茶山集级别） | 48 MB | 4.8 GB |
| 500 页古籍 | 48 MB | 24 GB |
| 1000 页古籍 | 48 MB | 48 GB（**OOM 风险**） |

实测：300 页 ZHSY 茶山集加载阶段 8.6 GB，swap 抖动明显。

### 当前临时缓解

`iter_pages` 内部其实是 generator（`_iter_pdf` 用 `yield`），但 `list()` 把它物化了。**底层能力已具备，只差调用方改一行。**

## 1. 目标

**B1**：内存从 O(N×page_size) → O(page_size) per page
- 不再 `list(iter_pages(...))`
- 主循环直接 `for page in tqdm(iter_pages(...))`
- paper_pages 采样改用 `itertools.islice`

**B2（顺手）**：outline 注入去 temp 文件，改用 `io.BytesIO`
- 当前 `_write_pdf_with_outline` 走 tempfile.NamedTemporaryFile（`pipeline.py:144`）
- img2pdf 支持 `output=` 字节流（v0.5+），可全内存拼接
- 100 MB PDF 节省 ~500ms 磁盘 I/O

## 2. 方案候选

### 方案 A：最小改动（推荐）

- 主循环直接迭代 generator
- paper_pages 采样：`list(islice(iter_pages(...), paper_pages_n))`
- 跳过 `list()` 物化 → 每页处理完即 GC 掉 PageInfo.image
- PDF 输出保持现有 "img2pdf → temp → pypdf" 2 步，但 temp 改为 BytesIO

**优点**：
- 改动最小（`pipeline.py` 主循环 + `_build_crop_config` 1 处 + `_write_pdf_with_outline` 1 处）
- 保留所有现有测试 + outline 注入逻辑
- 风险低

**缺点**：
- PDF 路径仍走 2 步（img2pdf + pypdf），不是真流式
- 大 PDF（1000 页）img2pdf 转换仍占 O(N) 内存（虽然只是中间产物）

**收益**：
- 内存：48GB → 200MB 稳态（**240× 改善**）
- 磁盘 I/O：100MB PDF 节省 ~500ms（B2）
- 1000 页古籍可处理

### 方案 B：PyMuPDF 全程输出

- `img2pdf` + `pypdf` → `pymupdf.Document` 单一引擎
- 每页处理完 → 转 pymupdf pixmap → `doc.insert_page()` 追加
- 末尾：`doc.set_toc()` + `doc.set_metadata()` + `doc.save()`

**优点**：
- 真流式（全程一个 doc，逐步 append）
- 无 temp 文件 / 无 BytesIO
- outline / metadata 在构建阶段直接 set，不需要后处理

**缺点**：
- **重大重构**：换 PDF 引擎
- PIL → pymupdf pixmap 转换需验证无信息丢失（vs img2pdf 无损）
- pymupdf PDF 输出 vs img2pdf 字节级对比需做
- outline 注入逻辑（mapping 处理）需重写为 set_toc 路径

**收益**：
- 比方案 A 更彻底的流式
- 但工作量大，风险高

### 决策

**先做方案 A**。理由：
- 用户的"v1.5 重点" 主要是"不 OOM"，方案 A 已达成
- 方案 B 是 v1.6+ 重构候选（依赖方案 A 落地验证流式可行性）
- 大重构风险高，需要 v1.4 outline 注入 + 大 PDF 真实数据回归

## 3. 方案 A 实施细节

### 3.1 改动清单

| 文件 | 改动 |
|---|---|
| `pipeline.py:run_pipeline` | 移除 `list(iter_pages(...))`，改为 `iter_pages(...)` 直接传给 tqdm |
| `pipeline.py:_build_crop_config` | 接受 `Iterable[PageInfo]` 而非 `list`；内部 `islice(iter, paper_pages_n)` |
| `pipeline.py:_write_pdf_with_outline` | temp 文件 → `io.BytesIO` |
| `tests/test_perf.py` | 加内存稳态基准（D1 扩展） |

### 3.2 关键代码（伪代码）

```python
def run_pipeline(args):
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input)

    # 1. 流式 iterator（不再 list 物化）
    page_iter = iter_pages(args.input)
    
    # 2. paper_pages 采样：islice 取前 N 个（一次性 list，可接受）
    paper_pages_n = max(1, getattr(args, "paper_pages", 5))
    crop_config = _build_crop_config(args, list(islice(page_iter, paper_pages_n)))

    # 3. outline / metadata 一次性抓取（独立于 page_iter，可并行做）
    ...

    # 4. 主循环：直接迭代
    image_paths: list[Path] = []  # 仅 PDF 输出累积；纯图模式不累积
    counter = 0
    for page in tqdm(page_iter, desc="切分"):
        ...  # 与现状一致
```

### 3.3 PDF 输出流式（B2 顺手）

当前 `_write_pdf_with_outline`：

```python
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp_path = Path(tmp.name)
try:
    save_pdf(image_paths, tmp_path)  # 写磁盘
    ...
    inject_outline_and_metadata(tmp_path, pdf_path, ...)  # 读磁盘 → 写磁盘
finally:
    tmp_path.unlink(missing_ok=True)
```

改成：

```python
import io
buf = io.BytesIO()
save_pdf_bytes(image_paths, buf)  # img2pdf 支持 output= 参数
buf.seek(0)
inject_outline_and_metadata_from_bytes(buf, pdf_path, ...)  # pypdf 直接读 BytesIO
```

**img2pdf API 验证**：`img2pdf.convert([paths], output=buf)` 是否支持？

需要查 img2pdf 0.6+ 文档确认 `output=` 参数。

### 3.4 outline mapping 累积

当前：
```python
if src_pdf_stem is not None and page.source_name == src_pdf_stem:
    outline_mapping[page.page_index] = list(range(counter, counter + len(sub_pages)))
```

流式版：完全相同（每次迭代独立 update mapping），无需改。

### 3.5 内存监控

实施后需加 `tracemalloc` 快照验证：
- v1.4 baseline：300 页加载阶段 ~8.6 GB
- 目标：< 500 MB 稳态

## 4. 风险

| 风险 | 严重度 | 缓解 |
|---|---|---|
| paper_pages 采样消耗部分页导致后续跳过 | 中 | islice 取的是 iterator 头部 N 个，剩余继续迭代（不丢页） |
| tqdm 进度条需要 total | 低 | `tqdm(iter, total=...)` 不知道总页数 → 用 `total=None`（动态显示） |
| PDF 输出进度无法估算 | 低 | 主循环完成后给 "合并 PDF..." 提示 |
| BytesIO img2pdf 兼容性 | 中 | 验证 0.5/0.6/0.7 img2pdf 的 `output=` 支持；若不支持退回 temp |
| 大 PDF pypdf 解析吃内存 | 中 | outline/metadata 抓取只在 PDF 输入 + PDF 输出时发生，且仅解析 metadata 不解析全页 |

## 5. 验证

### 5.1 单元测试

- 加 `test_streaming_memory_steady`：构造 100 页 mock，断言 tracemalloc peak < 500 MB
- 加 `test_pdf_via_bytesio_equivalent_to_tempfile`：跑一遍 PDF pipeline，对比两种路径输出 PDF 字节级一致
- 现有 88 测试零修改通过

### 5.2 真实数据回归

- 茶山集 132 页：内存峰值 < 500 MB（vs v1.4 ~3.5 GB）
- ZHSY 66 页：1.7s（保持 v1.5 Sprint 1 实测）
- 新增大 PDF 测试：构造 500 页 mock PDF（纯文字）跑通，验证不 OOM

### 5.3 内存基准

加 `tests/test_memory.py`（D 类扩）：

```python
def test_pipeline_memory_steady():
    """100 页 mock PDF：tracemalloc peak < 500MB."""
    import tracemalloc
    tracemalloc.start()
    ...run pipeline on 100-page mock...
    current, peak = tracemalloc.get_traced_memory()
    assert peak < 500 * 1024 * 1024, f"内存峰值 {peak/1024/1024:.0f}MB > 500MB"
```

## 6. 替代方案（不在本期）

- **PyMuPDF 全程输出**（方案 B）：v1.6+ 重构，需先验证 PIL→pymupdf 像素一致性 + pymupdf PDF 输出 vs img2pdf 字节级对比
- **Hough 结果缓存（A3）**：v1.5 候选
- **自适应 padding（C2）**：v1.5 候选

## 7. 时间估算

| 阶段 | 时间 |
|---|---|
| 代码改动 | 2-3h |
| 验证 img2pdf BytesIO 兼容性 | 0.5h |
| 加 memory 基准 test | 1h |
| 真实数据回归（茶山集 + ZHSY） | 0.5h |
| 文档 + session note | 0.5h |
| **总计** | **~5h** |

## 8. 后续

- Sprint 2 完成后，B1 + B2 标记为 ✅
- 下一个 sprint 候选：B3（Sauvola `sqrt(var)` 原地写，省 64MB 中间数组）
- 方案 B（PyMuPDF 全程）作为 v1.6 重构候选