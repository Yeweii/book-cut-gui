# 2026-06-21 · 切分 + 裁切鲁棒性增强：抗伤字 + 抗杂质（提案）

> 状态：提案，未实现
> 分支：待创建
> 拍板时间：2026-06-21
> 关联：v1.3 自适应裁切的延伸 + 优化 backlog C2（trim/paper 重复）+ v1.5 per-page paper override 的姊妹提案

## 1. 目标

古籍扫描件两类高频问题：

- **伤字**：切分时切到中缝附近的字符；裁切时切到版框/边距附近的字符
- **杂质**：外周空白有黑点 / 尘点 / 折痕 / 扫描噪点，裁切误判为"内容"

当前已部分防护（单页检测、padding、min_ink=3），但仍漏边界 case。本提案分两条线加固：

- **A 线 · 抗伤字**：gutter 用 p95 抗稀疏文字、crop padding 翻倍、加安全边距
- **B 线 · 抗杂质**：trim 用形态学开运算清除 1-3 像素尘点

## 2. 问题定义

### 2.1 切分 · gutter 误吞稀疏文字列

- 当前：`split/gutter.py:42` `col_means = arr.mean(axis=0)` + `min_white_value=220` + `min_run_width=10`
- 场景：古文竖排列稀疏（每列只有 1-2 个暗像素），列均值 200-220
- 后果：字符列被认作"白列" → gutter 检测落在字符上 → **切到字**

### 2.2 切分 · half 切偏中缝

- 当前：`split/half.py:13` `mid = w//2 + offset`（固定几何中心）
- 场景：扫描偏一边（双页未对齐到图像中心）或装订变形
- 后果：**必然切偏中缝，伤字**（offset 只是用户手动微调，不是自适应）

### 2.3 裁切 · 灰尘黑点触发"假内容"

- 当前：`detect/trim.py:62-69` legacy `min_ink=1`（**任一非白像素**）/ adaptive `min_ink=3`
- 场景：扫描外周有 1-10 像素黑点 / 尘点 / 折痕 / JPEG 噪点
- 后果：
  - **1-3 px 尘点**：legacy 必触发 / adaptive 部分触发 → crop 边界停在尘点 + padding
  - **5+ px 尘点**：必然触发 → crop 边界停在尘点 → **浪费边距**，字符不伤但页面"留白不均"
  - **10+ px 折痕**：可能跨越整行/列 → crop 边界停在折痕 → **可能伤字**

### 2.4 裁切 · 版框内字符贴边

- 当前：`detect/border.py:72` `padding=5`（版框内裁的固定内边距）
- 场景：4000×4000 高分辨率扫描，字符距版框 < 5px
- 后果：padding 不够 → 字符边缘被裁 → **伤字**

### 2.5 杂症汇总

| 现象 | 位置 | 严重度 |
|------|------|--------|
| gutter 切到字 | `split/gutter.py:71-101` | 高（伤字） |
| half 切偏中缝 | `split/half.py:13` | 高（伤字） |
| 1-3px 尘点停 crop | `detect/trim.py:62-69` | 中（不留白不均） |
| 5+ px 尘点停 crop | `detect/trim.py:62-69` | 中高（折痕可能伤字） |
| 版框 5px padding 太薄 | `detect/border.py:72` | 中（伤字） |
| trim 贴边时仍裁 | `detect/trim.py:84-87` | 低（pad=0 退化） |

## 3. 选型

### 3.1 抗伤字 · gutter 检测加固

| 候选 | 评估 | 选/拒 |
|------|------|------|
| **A1. 列 95th percentile 替代 mean** | 字符列 p95 通常 < 200（暗像素拉低），与"白列"（p95 ≥ 230）显著区分 | **选** |
| A2. 缩窄 search_range 0.4→0.2 | 远端稀疏文字不进搜索区，但**正中心紧贴字符的书救不了** | **选**（叠加 A1） |
| A3. min_run_width 10→20 | 要求更宽白段，防"假缝" | **选**（叠加 A1） |
| B. 切分时两侧留 overlap（3-5px）| 救不回来已切字符，只能救下游 crop | 拒（语义错位） |
| C. 加连通域分析判定"白段" | 过度设计，A1+A2+A3 已够 | 拒 |

### 3.2 抗伤字 · 裁切 padding + 安全边距

| 候选 | 评估 | 选/拒 |
|------|------|------|
| **A1. `border.crop_to_border` padding 5→10** | 翻倍保守，0 性能开销 | **选** |
| **A2. trim 加 "safety margin"** —— 检测到内容距图边 < min_safe_margin（短边 1% 或 5px）→ 不裁 | 贴边字符保护 | **选** |
| B. trim 加"内容密度梯度"检测（突然密集处才是真边界）| 过度设计，morphology 已可救 | 拒 |
| C. border crop padding 自适应（按短边 2%）| 与 trim adaptive padding 重复 | 拒 |

### 3.3 抗杂质 · trim 加形态学开运算

| 候选 | 评估 | 选/拒 |
|------|------|------|
| **A1. `cv2.morphologyEx(MORPH_OPEN)` on ink_mask** | 3×3 核清除 1-3 px 孤立尘点，文本连通域保留 | **选** |
| **A2. min_ink 1→3（legacy 与 adaptive 对齐）** | 单像素 JPEG 噪声基线 | **选** |
| B. 灰度中值滤波 `cv2.medianBlur(gray, 3)` | 对 trim 来说等价于 mask 开运算，但**会改变下游 binarize 看到的图** | 拒（破坏模块边界） |
| C. 连通域过滤 `connectedComponentsWithStats` | 精确但慢（~10ms/页），A1+A2 已覆盖 90% 场景 | 拒 |
| D. 距离变换 + 半径阈值 | 杀鸡用牛刀 | 拒 |

### 3.4 抗伤字 · half 切偏

| 候选 | 评估 | 选/拒 |
|------|------|------|
| A. 加 `--half-safety`（先 gutter 试一下，失败再 half）| 半切常因"扫描偏"才用，gutter 试一下能救一半 | 拒（增加复杂度，CLI 多一个开关） |
| B. half 切分前**先调用 gutter 估中心**，再 ±offset 微调 | 复用 gutter 逻辑，半切变"gutter 兜底" | 拒（破坏 half 简单语义） |
| **C. 文档明确"半切需扫描完全居中，不确定用 gutter"** | 0 改动，CLI help 加一句警告 | **选** |

## 4. 数据流

```
# A. gutter 加固（detect 阶段）
split_gutter(image)
  └─ find_gutter_column(image, search_range=0.2, min_white_value=230, min_run_width=20)
       ├─ col_p95 = np.percentile(arr, 95, axis=0)        # 替代 mean
       ├─ col_mean = arr.mean(axis=0)
       ├─ is_white = (col_p95[lo:hi] >= 230) & (col_mean[lo:hi] >= 220)
       └─ 找最长连续 True 段（同 v1.3）

# B. trim 加固（crop 阶段）
trim_margins(image, config=...)
  ├─ ink_mask = arr < ink_thr
  ├─ ink_mask = cv2.morphologyEx(ink_mask, MORPH_OPEN, 3x3)   # ← 新
  ├─ min_ink = max(1, config.min_edge_ink)   # legacy 也走 ≥3 路径
  ├─ row_has_content = ink_mask.sum(axis=1) >= min_ink
  ├─ col_has_content = ink_mask.sum(axis=0) >= min_ink
  ├─ safety_margin = max(5, int(min(h, w) * 0.01))
  ├─ if 边界距图边 < safety_margin → return image  # ← 新
  └─ crop(...)

# C. border crop 加固
crop_to_border(image, padding=10, config=...)
  └─ ...（其他逻辑不变）
```

## 5. 关键设计

### 5.1 gutter 用 p95 替代 mean（双判据）

字符列 vs 白列的灰度直方图（典型古籍扫描）：

| 列类型 | mean | p95 | 判据 (p95≥230 AND mean≥220) |
|--------|------|-----|----|
| 纯白（真中缝） | 250 | 255 | ✓ |
| 稀疏字符（每列 1-2 暗像素） | 215 | **180** | ✗ ← 救回来 |
| 浓密字符 | 100 | 200 | ✗ |
| 中等文字 | 180 | 230 | 取决于字符密度 |

**p95 ≥ 230 是关键判据**：白列最暗的 5% 像素仍 ≥ 230（白纸），稀疏文字列最暗 5% 像素 < 200（被字符拉低）。

```python
# detect/paper.py 加：
def _column_is_white(col_arr: np.ndarray, min_p95: float = 230.0, min_mean: float = 220.0) -> bool:
    """单列是否'白'：p95 + mean 双判据。"""
    return (np.percentile(col_arr, 95) >= min_p95) and (col_arr.mean() >= min_mean)
```

**风险**：极少数高对比度墨迹可能"穿透" p95 判据。缓解：与 search_range=0.2 叠加（只在最中心 ±10% 搜）。

### 5.2 trim 用形态学开运算清除尘点

```python
import cv2
ink_mask_u8 = ink_mask.astype(np.uint8)
ink_mask_clean = cv2.morphologyEx(
    ink_mask_u8,
    cv2.MORPH_OPEN,
    np.ones((3, 3), np.uint8),
).astype(bool)
```

3×3 开运算效果：
- 1 像素孤立点 → 清除
- 2 像素短线段 → 清除
- 3 像素 L 形 → 清除
- 3×3 实心块 → 保留
- 文字笔画（≥ 4 像素宽）→ 保留

**对古籍文字的兼容性**：
- 楷书 / 仿宋：笔画 ≥ 5px（300DPI 扫描）→ 安全
- 行书 / 草书：笔画 ≥ 3px → 大部分安全，1-2px 飞白可能消失（裁切时本来也看不见）
- 极小字（如 6pt 注疏）：300DPI 下 1-2px → **可能消失**（与"尘点"无法区分，物理上无法分辨）

**缓解**：CLI `--no-morph` opt-out（极端情况下用户可关）。

### 5.3 trim 加 safety margin（贴边保护）

```python
# 短边 1% 至少 5px
safety = max(5, int(min(h, w) * 0.01))

if (rows_idx[0] < safety or
    rows_idx[-1] > h - safety - 1 or
    cols_idx[0] < safety or
    cols_idx[-1] > w - safety - 1):
    return image  # 保守：不裁
```

4000×4000 图 → safety = 40px。贴边 40px 内的"内容"被认作"不可信" → 不裁。
3000×2000 图 → safety = 20px。
500×500 图 → safety = 5px（floor）。

**已知限制**：safety 内的真内容也会被保护（不被裁），但**这是有意的保守策略**（漏切 ≪ 误切）。

### 5.4 border crop padding 翻倍

```python
def crop_to_border(
    image: Image.Image,
    padding: int = 10,  # ↑ 5 → 10
    config: CropConfig | None = None,
) -> Image.Image:
```

理由：trim 的 adaptive padding 已能算到 30px，border 也对齐到 10-15 区间。

**注意**：padding 不影响 Hough 检测本身，只影响裁切坐标。0 性能开销。

### 5.5 half 切分 · 不动算法，加文档警告

```python
# cli.py --split half 的 help：
"--split half: 固定 w//2 切，**要求扫描严格居中**。不确定时请用 --split gutter（中缝自适应）。"
```

半切是"用户已知扫描居中时的快路径"，不需要算法加固。**算法层面 gutter 已经能 cover**。

### 5.6 morphology 与 A1（v1.5 单次 RGB→L）联动

A1 把 RGB→L 集中到 pipeline 入口，trim 收到的是 ndarray。morphology 直接在 ndarray 上跑：

```python
# A1 后
def trim_margins(arr: np.ndarray, config: CropConfig, ...) -> Image.Image:
    ink_mask = arr < config.ink_threshold
    ink_mask = cv2.morphologyEx(ink_mask.astype(np.uint8), cv2.MORPH_OPEN, ...)
    # ...
```

**现状（A1 未做）**：trim 自己 `image.convert("L")` + morphology 重复一次 → ~3ms 额外开销。
**A1 之后**：0 额外开销（morphology 在已转换的 ndarray 上跑）。

**实施顺序**：A1 必须先于本提案的 B 线（morphology），否则 B 线有 3ms × 500 页 = 1.5s 额外开销。

### 5.7 legacy `min_ink=1` 路径废弃

v1.6 起统一走 `min_ink >= 3` 路径。理由：
- legacy `min_ink=1` 在 JPEG 噪声下频繁误判（v1.1 时代就有 dust dot 问题）
- A2 提升到 3 后行为与 adaptive 一致
- 老 4 个 detect test 仍能通过（行为兼容：尘点变 ink 像素 ≥ 1 仍触发）

## 6. CLI / GUI 改动

### CLI

```python
# A. 调整默认参数（不新增 flag）
# gutter 默认已硬编码在函数里，改默认即可
# border crop padding 默认已硬编码，改默认即可

# B. 新增 opt-out
parser.add_argument(
    "--no-morph",
    action="store_true",
    help="关闭 trim 阶段的形态学开运算（古籍飞白/极小字可见时用）。"
    "默认开。",
)

# C. half 警告（不改逻辑，只改 help）
"--split": choices=["half", "gutter", "border"],  # help 文字加警告
```

### GUI

- "单页裁切" 行加 **抗杂质** 复选框（默认勾选，对应 `--no-morph` 反义）
- 页序下拉旁不动

## 7. 文件改动清单

| 文件 | 改动 |
|------|------|
| `src/book_cut/split/gutter.py` | `find_gutter_column` 改用 p95+mean 双判据；默认 `search_range=0.2, min_white_value=230, min_run_width=20` |
| `src/book_cut/split/half.py` | 不动；CLI help 加警告 |
| `src/book_cut/detect/trim.py` | `trim_margins` 加 morphology open + safety margin 检查；legacy `min_ink=1` 走 `>=3` 路径 |
| `src/book_cut/detect/border.py` | `crop_to_border` 默认 `padding=10` |
| `src/book_cut/detect/paper.py` | 加 `_column_is_white(col_arr, min_p95, min_mean)` 工具函数 |
| `src/book_cut/cli.py` | 新增 `--no-morph`；`--split` help 文字加 half 警告 |
| `src/book_cut/gui.py` | "单页裁切" 行加"抗杂质"复选框 |
| `tests/test_split_gutter.py` | 新增 4 个 test：稀疏文字列不被吞 / p95+mean 双判据 / 缩窄 search_range 行为 / CLI `--no-morph` 端到端 |
| `tests/test_detect.py` | 新增 5 个 test：morphology 清除尘点 / safety margin 贴边保护 / border padding 翻倍 / 极小字消失 opt-out / 大折痕不被吞 |
| `README.md` | 加"鲁棒性：抗伤字 + 抗杂质"段 |
| `tasks.md` | 加 v1.6 任务段 |
| `docs/sessions/2026-06-21-book-cut-v1.6.md` | 实现后写 |

## 8. 测试计划

### A. 切分抗伤字

| ID | 场景 | 期望 |
|----|------|------|
| T1 | 合成：双页图，**正中心紧贴 5px 字符** | p95<200 → 不被认作白列 → gutter 落在真正白段 |
| T2 | 合成：左页 80% 列均值 220（稀疏文字）| mean ≥ 220 但 p95 < 200 → 不被认作白列 |
| T3 | 真实：ZHSY（已知中缝干净）| gutter 位置 ±5px 之内（回归） |
| T4 | 真实：找一本"中缝附近有字"的书 | 切分不伤字（人工目测） |

### B. 裁切抗杂质

| ID | 场景 | 期望 |
|----|------|------|
| T5 | 合成：白底 + 边缘 5 个 1-3 px 黑点 | 形态学清除 → crop 到真内容 |
| T6 | 合成：白底 + 边缘 1 个 10×3 px 折痕 | morphology 清除折痕 → crop 到真内容（前提：折痕不跨整行） |
| T7 | 合成：白底 + 内容**贴图边**（< 5px）| safety margin 触发 → 不裁（返回原图） |
| T8 | 合成：300DPI 楷书 4-5px 笔画 | morphology 不影响 → 字符完整 |
| T9 | 合成：300DPI 极小字（6pt，1-2px 笔画）| 默认 ON 时可能消失；`--no-morph` 后保留 |
| T10 | 真实：ZHSY（已知无杂质）| 行为与 v1.3 一致（回归） |
| T11 | 真实：找一本"外周有尘点"的书 | crop 不被尘点阻挡 |

### C. 版框 padding 翻倍

| ID | 场景 | 期望 |
|----|------|------|
| T12 | 合成：版框内字符距版框 3px | padding=5 时字符被裁；padding=10 时保留 |
| T13 | 真实：茶山集（有版框）| 行为与 v1.3 一致或更紧（padding 增大） |

### D. 端到端性能

| ID | 场景 | 期望 |
|----|------|------|
| T14 | 500 页 + 所有加固 ON + A1 已做 | 耗时 ≤ v1.3 baseline + 5% |
| T15 | 500 页 + 所有加固 ON + A1 未做 | 耗时 ≤ v1.3 baseline + 15%（morphology 3ms × 500 = 1.5s） |

## 9. 风险与缓解

| 风险 | 缓解 | 严重度 |
|------|------|--------|
| morphology 吃掉古籍飞白 / 极小字 | CLI `--no-morph` opt-out；文档明确 trade-off | 中 |
| safety margin 导致贴边真内容不被裁 | "漏切 ≪ 误切"，用户可调 padding | 中 |
| gutter p95 阈值过严，真白列被拒 | p95 ≥ 230 + mean ≥ 220 双判据（白列 p95=255 不会拒） | 低 |
| border padding 10 影响版框靠近的稀疏图 | padding 仅用于裁切坐标，不影响 Hough 检测 | 低 |
| half 切偏仍无解 | 文档警告；推荐 gutter | 低（保留 half 为 opt-in） |
| 与 v1.5 per-page paper override 冲突 | v1.5 改 ink_thr，本提案改 trim/border 的 padding，**正交** | 低 |
| 与 A1 重构时序 | 强制 A1 先做（避免 morphology 性能损失） | 中 |
| 4 个老 detect test 行为变化 | legacy `min_ink=1` → 3，尘点 1px 不再触发；测尘点用 `mock` 数据，回归 OK | 低 |

## 10. 已知限制

1. **极小字（6pt 注疏）与尘点物理上不可分** —— 1-2px 笔画 = 1-2px 黑点
   - 用户只能用 `--no-morph` 二选一（保留极小字 vs 抗尘点）
2. **gutter p95 阈值是经验值**（230）—— 极少数高对比度墨迹（朱砂 / 印泥）可能"穿透"
   - 配合 search_range=0.2 限定在中心 ±10% 搜
3. **safety margin 是保守策略** —— 贴边真内容会"漏切"
   - 用户可调 padding（CLI/GUI spinner）补回
4. **morphology 3×3 核是固定值** —— 大图/小图通用，但对**分辨率极不均匀**的书（同一本内 300DPI + 600DPI 混排）不友好
   - 解决：v1.7 候选 —— 按 DPI 调核大小
5. **half 切偏靠文档解决** —— 不改算法
6. **本提案不覆盖 deskew 后的倾斜字符**（"半字压在裁切线上"）—— v1.7 候选
7. **不覆盖 v1.5 per-page paper override**（互不依赖，可独立做）

## 11. 实施顺序

1. **A1 单次 RGB→L**（v1.5 sprint 1，先做）
2. **D1 性能基准**（v1.5 sprint 1，量化"v1.3 baseline"）
3. **本提案 B 线（morphology + safety margin）**（v1.6 sprint 1）：
   - `trim.py` 加 morphology + safety margin + 统一 `min_ink ≥ 3`
   - `paper.py` 不动（trim 独立）
   - 5 个 test
   - ZHSY 回归 + 合成 5 张图测试
4. **本提案 A 线（gutter p95 + border padding）**（v1.6 sprint 1，可与 B 线并行）：
   - `gutter.py` 改 p95+mean 双判据 + 默认参数调整
   - `border.py` padding 5→10
   - 4 个 test
5. **CLI/GUI + 文档**（v1.6 sprint 1 末尾）
6. **v1.5 per-page paper override**（v1.5 sprint 2，依赖 A1）
7. **真实数据验证**（sprint 2）：茶山集 + ZHSY + 找一本"中缝紧贴字符"的书

## 12. 后续

- v1.7 候选：按 DPI 自适应 morphology 核大小
- v1.7 候选：deskew 后倾斜字符的裁切安全检查
- v1.7 候选：连通域过滤替代 morphology（更精确但慢）
- v2 候选：OCR 后处理检测"字符是否被裁切"（基于字符识别置信度）
- v2 候选：自适应"中缝候选"评分（多特征：白度 + 长度 + 对称性 + 上下文连续性）
