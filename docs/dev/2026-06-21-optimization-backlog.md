# 2026-06-21 · 优化 Backlog（v1.5+ 候选池）

> 状态：未开始。挑哪个做时单独开 proposal（`docs/dev/YYYY-MM-DD-v1.5-<name>.md`）。
> 拍板时间：2026-06-21
> 基准：133 页 ZHSY v1.3 实测 21s（~160ms/页）

## 0. 基准（hot-path 单页耗时，4000×4000 RGB）

| 操作 | 耗时/页 |
|---|---|
| `PIL.Image.convert("L")` | 2.5ms |
| `np.asarray(L, float32)` | 7.0ms |
| `arr < threshold`（uint8 掩码） | 0.3ms |
| `cv2.Canny` | 1.5ms |
| `cv2.HoughLinesP`（含 Canny） | ~5.5ms |
| `cv2.boxFilter 25×25` float32 | 15.5ms |
| `arr * arr` 物化（Sauvola 预乘） | 1.1ms |
| `cv2.sqrBoxFilter 25×25`（融合） | 18.8ms |

133 页流水线触发 `convert("L")` ×4-5、boxFilter ×2 → ~25ms/页纯冗余 ≈ 3.3s 浪费 / 133 页。

## 1. 优先级总览

| # | 类别 | 项 | 预估收益 | 难度 | 建议 |
|---|------|----|----------|------|------|
| 🟢 A2 | 性能 | Sauvola `sqrBoxFilter` 融合 | 省 64MB 内存 + 1ms/页 | **低**（1 行） | **v1.5 第一个** |
| 🟢 A1 | 性能 | 流水线单次 RGB→L | 133 页省 1.6s | 中（重构） | **v1.5 第一个** |
| 🟢 B1 | 内存 | 流式 `iter_pages` | 1000+ 页古籍可用 | 中（重写主循环） | **v1.5 重点** |
| 🟡 A3 | 性能 | Hough 结果缓存（split+crop 联动） | 3-5% 提速 | 低 | v1.5 |
| 🟡 B2 | 内存 | outline 注入改 BytesIO | 大 PDF 提速 | 低 | v1.5 |
| 🟡 D1 | 测试 | 加性能基准 `test_perf.py` | 防回归 | 低 | **v1.5 第一个**（与 A1+A2 同步） |
| 🟡 D2 | 测试 | 边界用例（0 页、损坏、非标尺寸） | 错误处理 UX | 低 | v1.5 |
| 🟡 C1 | 质量 | 抽 Hough 公共模块 | 减 80 LOC | 中 | v1.5 |
| 🔵 A4 | 性能 | `_resolve_outline_source` 双调 | 微优化 | 低 | 顺手 |
| 🔵 A5 | 性能 | deskew projection 降分辨率 | 0.5-1s/页 | 中 | v1.6 |
| 🔵 C2-C5 | 质量 | trim/paper/拆分/参数集中 | 可读性 | 中 | v1.6 |
| 🔵 E1-E3 | UX | GUI 错误友好化 + 进度 + 完成总结 | UX | 低 | v1.5 |

## 2. A · 性能

### A1. 流水线单次 RGB→L 转换

**现状**（每页 4-5 次重复转换）：
- `deskew.to_gray_array`（`preprocess/deskew.py:16`）
- `split_gutter._to_gray_array`（`split/gutter.py:12`）
- `is_single_page._to_gray_array`（`detect/single_page.py:22`）
- `crop_to_border._to_gray`（`detect/border.py:20`）
- `trim_margins.convert("L")`（`detect/trim.py:44`）
- `binarize._to_gray_array`（`preprocess/binarize.py:11`）

**触发条件**：开 `--deskew --split gutter --crop border --binarize sauvola` 时单页 5 次。

**改法**：
1. pipeline 在 `deskew` 后做一次 `img.convert("L")` + `np.asarray(arr, dtype=np.uint8)`
2. 把这个 ndarray 通过参数传到各 detect/split/crop/binarize 函数
3. 函数签名统一：`fn(arr: np.ndarray, ...) -> np.ndarray | Image`
4. 最后 binarize 转回 PIL Image 输出

**风险**：
- 改 6 个函数的签名（向后兼容 → 加 `image: Image.Image | np.ndarray` Union type）
- bbox 调用点必须正确转换（已切分后的 sub_pages 仍是 PIL Image）
- 测试需要回放全部 65 个 + 1 个 perf 回归测试

**验证**：
- 现有 65 测试零修改通过
- 性能基准：单页 < 200ms（v1.3 160ms；A1 改完应 < 145ms）

---

### A2. Sauvola `sqrBoxFilter` 融合

**状态**：✅ v1.5 已实现（**平台后端选择**，非纯替换）

**原始提案**（`preprocess/binarize.py:71`）：
```python
# 旧
mean_sq = cv2.boxFilter(arr * arr, -1, ksize)  # 物化 64MB 临时

# 原提案：直接换
mean_sq = cv2.sqrBoxFilter(arr, -1, ksize)  # 融合
```

**实测发现（macOS arm64，2026-06-21）**：sqrBoxFilter 在 arm64 NEON 上**反而慢 27-80%**：
- boxFilter(arr*arr)  2000×2000 = 15.7-16.8ms / 4000×4000 = 61.3-68.3ms ✓
- sqrBoxFilter(arr)   2000×2000 = 19.9-21.4ms / 4000×4000 = 79.8-98.3ms ✗

原因推测：OpenCV arm64 NEON 对 `boxFilter` 高度优化（multiply + filter 两次 SIMD pass），`sqrBoxFilter` 无同等优化路径。x86_64 AVX 可能反过来，但 80% 用户在 arm64。

**最终方案（v1.5 落地）**：
- 平台自动：`platform.machine() in {"x86_64", "AMD64", ...}` → sqrBoxFilter；其他 → boxFilter
- 环境变量 `BOOKCUT_BINARIZE={sqrbox,box}` 覆盖默认
- 0 行数性能损失（arm64 默认 box = v1.4 baseline），x86 节省 64MB 内存
- 3 个 test 验证：`test_backend_default_matches_platform` / `test_backend_env_box_override` / `test_backend_env_sqrbox_override`

**后续**：v1.7 候选 —— x86 实测确认 AVX 优势；如确认则在 x86 上内存节约更显著

**风险**：
- 浮点精度有微小变化（squared sum vs sqrBoxFilter 内部累加顺序）
- 极少数极端高对比度图可能产生 1-2 像素差异
- 触发：所有走 Sauvola 的页面

**验证**：
- ZHSY 132 图 + 茶山集 136 图，pymupdf 渲染对比 v1.4 像素级
- diff < 0.1% 像素（容差 1 个灰度级）

---

### A3. Hough 结果缓存（`--split border --crop border` 联动）

**现状**：
- `split_border.find_border_split`（`split/border.py:18-94`）：Canny + HoughLinesP + cluster
- `crop_to_border._detect_lines`（`detect/border.py:26-67`）：同样的 Canny + HoughLinesP + cluster
- 同一张图跑两次，触发条件 `--split border --crop border`（用户偶用）

**改法**：
- 抽 `_hough_common.detect_hough_lines(gray, threshold=80, min_length_factor=20) -> list[(x1,y1,x2,y2)]`
- 抽 `_hough_common.cluster_lines(lines) -> list[(vs, hs)]`
- 两个 caller 复用，参数不同通过 kwargs 传

**风险**：
- 拆分后函数调用略增（5% ↑？需测）
- cluster 逻辑两边略有差异（padding/factor 不同），需保留

**收益**：
- `--split border --crop border` 用户：单页省 4ms
- 减 ~80 LOC 重复代码

---

### A4. `_resolve_outline_source` 双调

**现状**（`pipeline.py:108` + `pipeline.py:116`）：
- 第一次取 `(src_pdf, is_multi)` 用 print
- 第二次再 is-not-None 判断取 `stem`

**改法**：
- 一次调用，结构 `(src_pdf, is_multi) = _resolve_outline_source(input_path)`，复用 `src_pdf.stem`

**收益**：微小（省 1 个 is_pdf 遍历）

---

### A5. deskew projection 降分辨率搜索

**现状**（`preprocess/deskew.py:80-107`）：
- 32 次 `cv2.warpAffine` on full image，每次 15-30ms
- 总 500ms-1s/页

**改法**：
- 降采样到 400px 宽做粗搜+精搜（视觉角度不变）
- 找到角度后只 rotate 一次原图

**风险**：
- 极小图（< 400px）需要护栏
- 投影方差归一化要在降采样后做（值域变了但 argmax 不变）

**收益**：deskew 路径省 0.5-1s/页

---

## 3. B · 内存

### B1. 流式 `iter_pages`（最关键）

**现状**（`pipeline.py:96`）：
```python
pages: list[PageInfo] = list(iter_pages(args.input))  # 全量加载！
```

4000×4000 RGB = 48MB/页。1000 页 = 48GB 流量（实际是 ~24GB 峰值 + GC），1000 页直接 OOM。

**改法**：
1. 保持 `iter_pages` 是 Iterator
2. 用 `itertools.islice(iter_pages, paper_pages_n)` 采样前 N 页估 paper color
3. 主循环 `for page in iter_pages(...)` 流式处理
4. `image_paths` 必须改成"每页处理完立即 img2pdf 拼接"——但 img2pdf 不支持流式

**img2pdf 流式方案**：
- 改用 `img2pdf.convert([path])` 逐页写 + `pypdf` 后合并
- 或：pymupdf 自己写 PDF（v1.4 已用 PyMuPDF 加载，可以延伸用它写）

**风险**：
- 重大重构，影响 PDF 合并 + outline 注入的整套流程
- 需 v1.5 第一个 sprint + 大量回归

**收益**：
- 1000+ 页古籍可处理（最大 24GB → 200MB 内存稳定）
- 内存压力下降 100×

---

### B2. outline 注入改 BytesIO

**现状**（`pipeline.py:156-178`）：
- `img2pdf` → 写 tmp → `pypdf` 读 tmp → 写 final
- 100MB+ PDF 两次磁盘 I/O

**改法**：
```python
import io
buf = io.BytesIO()
img2pdf.convert([...], output=buf)  # 需 img2pdf 支持 output 参数
buf.seek(0)
pypdf.PdfReader(buf).pages → writer
```

**风险**：
- img2pdf 0.6+ 支持 `output=` 参数，确认 API
- 内存峰值 ×2（中间 PDF 进 RAM）

**收益**：
- 100MB PDF：2 次磁盘 I/O（~500ms）→ 0（纯内存）
- 与 B1 同步，内存增加可接受

---

### B3. Sauvola `sqrt(var)` 原地写

**现状**（`binarize.py:74`）：
```python
var = np.maximum(mean_sq - mean * mean, 0.0)  # 64MB
std = np.sqrt(var)  # 又 64MB
```

**改法**：
- 用 `cv2.subtract(mean_sq, mean*mean, dst=var)` 原地减
- `cv2.sqrt(var, dst=std)` 原地开方
- 或：`cv2.magnitude` 融合

**收益**：省 64MB 中间数组

---

## 4. C · 代码质量

### C1. Hough 公共模块
见 A3 描述。

### C2. trim.py 的 `_default_adaptive_padding` 重复
**现状**（`detect/trim.py:96-103`）：与 `detect/paper.py::adaptive_padding` 公式完全相同。
**改法**：解除 paper→trim 循环 import 关系，让 trim 直接调用 `adaptive_padding(h, w)`。
**风险**：需要审 paper 模块是否反向 import trim（当前没有）。

### C3. pipeline.py 单文件 263 行
**改法**：拆
- `pipeline/orchestrator.py`（run_pipeline + 主循环）
- `pipeline/outline.py`（v1.4 注入逻辑：mapping + 反转 + 写 PDF）
- `pipeline/crop_config.py`（`_build_crop_config` + paper 采样）

**收益**：单测可独立 mock outline。

### C4. Hough 参数分散
threshold = 60（border）vs 80（deskew/split），minLineLength factor 不同。
**改法**：抽 `detect/_hough_config.py` 提供 `HOUGH_BORDER` / `HOUGH_DESKEW` / `HOUGH_SPLIT` 常量。
**远期**：v1.6 做自适应（memory 已提"v1.4 候选"，本表升 v1.6）。

### C5. STANDARD_METADATA_KEYS 硬编码
**改法**：从 pymupdf 导入源 + 写转换函数 `to_pypdf_info_keys(pymupdf_meta)`。

---

## 5. D · 测试覆盖

### D1. 性能基准 `tests/test_perf.py`（**v1.5 第一个做**）

```python
def test_pipeline_perf_page():
    """4000x4000 双页图：端到端 < 300ms（v1.3 ~160ms 留余量）。"""
    img = synthesize_4000x4000_double_page()
    t = time.perf_counter()
    run_splitter(img, split='gutter', crop='border', binarize='sauvola')
    assert (time.perf_counter() - t) * 1000 < 300
```

**目的**：A1+A2 改完跑这个，能立即看到收益；以后任何改动跑这个能防退化。

### D2. 边界用例
- 0 页 PDF：`iter_pages` 返空
- 损坏 PDF：明确错误信息，不 crash
- 非标尺寸：3708×3862、4288×3330（memory 提过真实扫描件）
- `--paper-pages 0`：兜底路径
- `--paper-pages > total pages`：clamp 到实际页数

### D3. border 路径完整覆盖
- `split_border` Hough 失败 → fallback `split_half`（`split/border.py:105`）
- `crop_to_border` 3 处 fallback to trim（`detect/border.py:90, 97, 107`）
- `--split border --crop border` 联动（Hough 跑两次 → A3 改完跑这个）

### D4. deskew 各方法
- `method='hough'`：Hough 角度 < 0.5°
- `method='projection'`：投影方差最大角度
- `method='auto'`：Hough 失败 → projection 兜底
- angle < 0.1° → return 原图（早返回优化）

---

## 6. E · UX

### E1. GUI 错误信息友好化
**现状**（`gui.py:64`）：`f"❌ {e}"` 直接抛 exception 文本。
**改法**：加 `_format_error(e: Exception) -> str` 翻译常见错误（FileNotFoundError、cv2.error、img2pdf.PdfError）。

### E2. GUI 完成总结
**改法**：处理完后弹 `messagebox.showinfo` 显示"X 张图 + Y 节点 outline + 耗时 Zs"。

### E3. GUI 进度条 determinate
**改法**：把 `ttk.Progressbar(mode='indeterminate')` 改为 determinate，按 step/total 更新。

---

## 7. v1.5 切入点建议

**Sprint 1（1-2 天）**：D1 + A2 + A1
- D1 性能基准先立起来，量化"v1.3 baseline 160ms/页"
- A2 一行改动，省 64MB 内存，立即见效
- A1 重构 6 个函数签名，拿到 ~10% 提速
- D2 边界用例 + D3 border 路径覆盖（防回归）

**Sprint 2（2-3 天）**：B1 + B2
- 流式 pipeline，最大头重构
- BytesIO 替换 tempfile
- 1000+ 页古籍可处理

**Sprint 3（可选）**：C1 + A3 + C2-C5
- Hough 公共模块
- 代码质量清理

**v1.5 候选（非本 backlog）**（来自 memory）：
- page labels 拆分（罗马数字 → "i (右), ii (左)..."）
- 多 PDF outline 智能合并（按 source_name 作为一级目录）
- `--outline-mode {first,right,left,dup}` 切换指向策略

---

## 8. 后续

- 拍板先做哪几项 → fork 出 `docs/dev/YYYY-MM-DD-v1.5-<name>.md` 提案
- 实施时按 v1.4 流程：propose → apply → verify
- 性能基准（D1）必须先于 A1+A2 完成（否则改完不知道效果）
