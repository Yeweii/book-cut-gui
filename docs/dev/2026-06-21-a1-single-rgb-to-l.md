# 2026-06-21 · A1 流水线单次 RGB→L 转换（提案）

> 状态：提案，待 review
> 分支：待创建（v1.5 A1）
> 拍板时间：2026-06-21
> 关联：optimization-backlog §2 A1 + v1.6 split-crop 鲁棒性 + v1.5 per-page paper override 的共同前置

## 1. 目标

消除"每页 4-5 次重复 RGB→L 转换"的浪费：

- 现状：5 个函数各自 `convert("L")` + `np.asarray(...)`，单页 5 次 ≈ 12.5ms 浪费
- 133 页 = 1.6s 浪费
- 目标：pipeline 入口做 1 次 RGB→L，**所有 detect/split/crop/binarize 函数消费 ndarray**

**约束**（来自 backlog §2 A1 风险段）：
- 现有 65 个测试**零修改**通过
- 性能基准：单页 < 145ms（v1.3 baseline 160ms 留 10% 余量）

## 2. 现状（6 个 RGB→L 站点）

| # | 文件 | 行 | 函数 | 触发 |
|---|------|----|------|------|
| 1 | `preprocess/deskew.py` | 16 | `to_gray_array` | `--deskew` |
| 2 | `split/gutter.py` | 12 | `_to_gray_array` | `--split gutter` |
| 3 | `detect/single_page.py` | 22 | `_to_gray_array` | auto（`is_single_page`） |
| 4 | `detect/border.py` | 20 | `_to_gray` | `--crop border` |
| 5 | `detect/trim.py` | 44 | `trim_margins` 内联 | `--crop trim/border` |
| 6 | `preprocess/binarize.py` | 10 | `_to_gray_array` | `--binarize *` |

全开时（`--deskew --split gutter --crop border --binarize sauvola`）单页触发 **5 次**（单页检测仅在 split 内部触发，计数算入 #2）。

## 3. 选型

| 候选 | 评估 | 选/拒 |
|------|------|------|
| **A. 加 `*_from_array` 私有变体** | 公共 API 零变化，65 个 test 零修改；pipeline 用 `_from_array` 热路径 | **选** |
| B. 改公共签名 `image: Image \| np.ndarray` | 简洁但要 `isinstance` 分支；类型检查可能报错 | 拒（破坏向后兼容原则） |
| C. 把 `np.asarray` 提到 pipeline 之外 | 需要新 abstraction 层，过度设计 | 拒 |
| D. 走 cython/numba 路径 | 复杂度爆炸 | 拒 |

**A 方案核心**：每个公共函数加一个 `_from_array` 私有变体（接受 `np.ndarray`），内部逻辑相同但跳过 `convert("L")`。公共 API 不变。

## 4. 关键设计

### 4.1 私有 `_from_array` 变体命名规范

- 后缀 `_from_array`：清晰表达"接受 ndarray，不是 Image"
- 私有（下划线开头）：明确"pipeline 内部使用"
- 返回类型与原函数一致（多数返回 `Image`，少数返回 `arr`）

### 4.2 9 个函数清单

| # | 原函数 | 新变体 | 返回 | 备注 |
|---|--------|--------|------|------|
| 1 | `deskew(image)` | `deskew_from_array(arr)` | `Image` | 旋转在 arr 上做后转回 Image |
| 2 | `split_gutter(image)` | `split_gutter_from_array(arr)` | `list[Image]` | 切分用 arr 切片，结果转回 Image |
| 3 | `split_border(image)` | `split_border_from_array(arr)` | `list[Image]` | Hough 在 arr 上跑，结果转回 Image |
| 4 | `split_half(image)` | `split_half_from_array(arr)` | `list[Image]` | 简单切片 |
| 5 | `is_single_page(image, gutter_x)` | `is_single_page_from_array(arr, gutter_x)` | `bool` | 纯检查 |
| 6 | `crop_to_border(image)` | `crop_to_border_from_array(arr)` | `Image` | Hough + arr 切片 |
| 7 | `trim_margins(image)` | `trim_margins_from_array(arr)` | `Image` | 全部逻辑已在 arr 上 |
| 8 | `binarize_otsu(image)` | `binarize_otsu_from_array(arr)` | `Image` | |
| 9 | `binarize_adaptive(image)` | `binarize_adaptive_from_array(arr)` | `Image` | |
| 10 | `binarize_sauvola(image)` | `binarize_sauvola_from_array(arr)` | `Image` | |

**实现要点**：
- 公共函数 = 简单包装：convert + 调 `_from_array` + 包回 Image
- `_from_array` 内部去掉 `convert("L")` 调用
- 返回 Image 的函数用 `_to_L_image` 工具函数（已有）

### 4.3 pipeline 入口统一做 1 次转换

```python
# pipeline.py 主循环
img = page.image  # PIL Image（deskew 之后）
arr = np.asarray(img.convert("L"), dtype=np.uint8)  # ← 唯一一次

# 下游全部用 ndarray
if deskew:
    arr = deskew_from_array(arr)  # 接受 arr，返回 arr 或 Image
left, right = split_gutter_from_array(arr)  # 返回 list[arr]（hot path）
left = trim_margins_from_array(left)
right = trim_margins_from_array(right)
left = binarize_sauvola_from_array(left)
right = binarize_sauvola_from_array(right)
```

**关键设计点**：
- `split_gutter_from_array` 返回 `list[arr]`（不是 `list[Image]`），避免子页重复转回 Image
- 子页在 crop + binarize 阶段保持 ndarray
- binarize 阶段统一转回 Image（用户面向的输出）

### 4.4 dtype 一致性

- pipeline 入口：`uint8`（节省内存 + 抗 round-trip 误差）
- 所有 `_from_array` 内部用 `uint8` 即可（不需要 `float32`，已是灰度）

### 4.5 与 A2 联动

A2 改了 Sauvola 的均方后端（`boxFilter` vs `sqrBoxFilter`）。A1 把 RGB→L 集中后，A2 路径不变，但 **A1 后 A2 的临时数组 `arr * arr`（boxFilter 路径）能直接用 uint8**，省 2x 内存（原 64MB float32 → 32MB uint8）。

## 5. 数据流

```
旧（每页 5 次 RGB→L）：
  deskew(image)            → .convert("L") + 旋转 + 返 Image
  split_gutter(image)      → .convert("L") + 切分 + 返 list[Image]
    is_single_page(image)  → .convert("L") + 检查
  crop_to_border(image)    → .convert("L") + Hough + 返 Image
  trim_margins(image)      → .convert("L") + 裁切 + 返 Image
  binarize_sauvola(image)  → .convert("L") + sauvola + 返 Image

新（每页 1 次 RGB→L）：
  arr = np.asarray(image.convert("L"), dtype=np.uint8)   # ← 唯一一次
  arr = deskew_from_array(arr)                            # arr → arr（旋转后仍是 ndarray）
  left_arr, right_arr = split_gutter_from_array(arr)      # arr → list[arr]
  left_arr = crop_to_border_from_array(left_arr)          # arr → Image
  right_arr = crop_to_border_from_array(right_arr)
  left = trim_margins_from_array(left_arr)                # arr → Image
  right = trim_margins_from_array(right_arr)
  left = binarize_sauvola_from_array(left)                # arr → Image（binarize 转回）
  right = binarize_sauvola_from_array(right)
```

## 6. CLI / GUI 改动

无新 CLI flag、无 GUI 改动。**完全透明的优化**。

环境变量已存在（`BOOKCUT_BINARIZE`，A2 引入），继续生效。

## 7. 文件改动清单

| 文件 | 改动 |
|------|------|
| `src/book_cut/preprocess/deskew.py` | 加 `deskew_from_array(arr) -> np.ndarray`（旋转后仍返 ndarray） |
| `src/book_cut/split/gutter.py` | 加 `split_gutter_from_array(arr) -> list[np.ndarray]`；`is_single_page` 内部用 `is_single_page_from_array` |
| `src/book_cut/split/border.py` | 加 `split_border_from_array(arr) -> list[np.ndarray]` |
| `src/book_cut/split/half.py` | 加 `split_half_from_array(arr) -> list[np.ndarray]` |
| `src/book_cut/detect/single_page.py` | 加 `is_single_page_from_array(arr, gutter_x) -> bool` |
| `src/book_cut/detect/border.py` | 加 `crop_to_border_from_array(arr) -> Image` |
| `src/book_cut/detect/trim.py` | 加 `trim_margins_from_array(arr) -> Image` |
| `src/book_cut/preprocess/binarize.py` | 加 3 个 `binarize_*_from_array(arr) -> Image`；`binarize` 内部加 `binarize` 分派支持 arr 路径（可选） |
| `src/book_cut/pipeline.py` | 主循环改造：1 次 `convert("L")` → arr → 串 `_from_array` 链 |
| `tests/test_binarize.py` | +2 test：`binarize_sauvola_from_array` 返 Image 形状正确 + Image 路径输出像素一致 |
| `tests/test_split.py` | +1 test：`split_gutter_from_array` 返 list[ndarray] 形状正确 |
| `tests/test_detect.py` | +1 test：`trim_margins_from_array` 行为与 Image 路径一致 |
| `tests/test_perf.py` | 加全流水线性能测试 `test_pipeline_full_4000_perf`（deskew + split + crop + binarize 串行） |
| `README.md` | 加"A1 单次 RGB→L 优化"段（简短，1 段） |
| `docs/sessions/2026-06-21-book-cut-v1.5.md` | 实现后写（v1.5 sprint 1 总结） |

**0 老 test 被修改**（v1.4 docstring 承诺）。

## 8. 测试计划

### A. 行为对等（公共 API vs `_from_array`）

| ID | 场景 | 期望 |
|----|------|------|
| T1 | `trim_margans(image)` vs `trim_margins_from_array(np.asarray(image.convert("L")))` | 输出 Image 像素值完全一致 |
| T2 | `binarize_sauvola(image)` vs `binarize_sauvola_from_array(arr)` | 同上 |
| T3 | `split_gutter(image)` vs `split_gutter_from_array(arr)` | 两张子页 Image 像素值完全一致 |
| T4 | `crop_to_border(image)` vs `crop_to_border_from_array(arr)` | 同上 |
| T5 | `is_single_page(image, x)` vs `is_single_page_from_array(arr, x)` | bool 值完全一致 |

### B. 端到端（pipeline 串行）

| ID | 场景 | 期望 |
|----|------|------|
| T6 | 合成 2000×2000 双页 → 走 pipeline 全开 | 输出 2 张 Image + 数值与 v1.4 像素级一致 |
| T7 | 合成 4000×4000 双页 → 走 pipeline 全开 | 同上 + 耗时 < 145ms（v1.3 160ms baseline - 10%） |

### C. 回归

| ID | 场景 | 期望 |
|----|------|------|
| T8 | 65 个老 test 零修改全过 | ✓ |
| T9 | D1 perf baseline 不退化（Sauvola 2000 < 500ms / 4000 < 800ms）| ✓ |

### D. 性能验证

| ID | 场景 | 期望 |
|----|------|------|
| T10 | arm64：全流水线 4000×4000 测 3 次 | 较 v1.3 baseline 节省 ~10-15ms/页（5 次 convert → 1 次） |
| T11 | arm64：ZHSY 66 页全跑 | 总耗时 ≤ v1.3 21s - 1.6s ≈ 19.4s |

## 9. 风险与缓解

| 风险 | 缓解 | 严重度 |
|------|------|--------|
| `_from_array` 与公共 API 行为漂移 | T1-T5 行为对等 test + 像素级比较 | 中 |
| arr 切片 vs Image.crop 边界差 | 公开承诺用 `arr[top:bottom+1, left:right+1]`（+1 等价于 PIL Image.crop 的 right+1） | 低 |
| dtype 不一致（uint8 vs float32）| pipeline 入口统一 uint8；`_from_array` 内部用 `arr.astype(np.float32)` 仅在 Sauvola 算 std 时（已存在） | 低 |
| 公共函数变成薄包装层 | 文档 + docstring 明确"wrapper around `_from_array`" | 低 |
| 改 6 个文件 × 9 个函数签名（语义不变）| 65 test 零修改 + T1-T5 行为对等 test 防漂移 | 中 |
| 与 A2 / v1.5 per-page paper override 时序 | A1 先做；A2 已落地；v1.5 per-page paper override 提案 §5.3 明确"用 A1 后的 arr" | 低 |
| 性能提升不及预期（arm64 NEON 对 convert("L") 已有优化）| D1 perf test 立 baseline，T10/T11 量化提升；如无提升则接受（仍省 4 次冗余 convert） | 低 |
| `deskew_from_array` 旋转后 arr 内存布局 | 用 `np.ascontiguousarray` 显式连续（防 cv2.warpAffine 失败） | 低 |

## 10. 已知限制

1. **8bpp 灰度假设**：A1 后 pipeline 假设输入是 RGB，输出灰度。**不支持 RGBA / palette / CMYK 输入** —— 这些模式仍走公共函数（`convert("RGB")` → `convert("L")`）
   - 现状：v1.1-v1.4 也只支持 RGB
2. **A1 仅优化 v1.4 默认 hot path**（`--deskew --split gutter --crop border --binarize sauvola`）
   - 其它组合（`--split half` 等）也享受优化
3. **`_from_array` 不替代 `_to_gray_array` 私有 helper**：私有 helper 仍存在（被 `_from_array` 内部用 + 公共函数内部用）
4. **公共函数 `_from_array` 命名约定**：v1.7 候选 —— 改 `*_arr` 命名空间（与 Rust 风格一致）

## 11. 实施顺序

1. **写 helper `_to_L_image` 确认**（已有，跳过）
2. **trim_margins_from_array**（最简单，Image 路径已全在 arr 上）—— **sprint 1 第 1 步**
3. **binarize_*_from_array**（简单，纯 ndarray 运算）—— **sprint 1 第 2 步**
4. **is_single_page_from_array + split_gutter_from_array**（核心 hot path 之一）—— **sprint 1 第 3 步**
5. **split_border_from_array + split_half_from_array**（hot path 补全）—— **sprint 1 第 4 步**
6. **crop_to_border_from_array**（涉及 Hough + arr 切片）—— **sprint 1 第 5 步**
7. **deskew_from_array**（旋转 + 仍返 ndarray）—— **sprint 1 第 6 步**
8. **pipeline.py 改造**（每步可独立 commit）—— **sprint 1 第 7 步**
9. **test 补全**（T1-T11）—— **sprint 1 第 8 步**
10. **D1 perf test 加全流水线用例**（量化收益）—— **sprint 1 第 9 步**
11. **真实数据验证**（ZHSY 66 页 + 茶山集 133 页）—— **sprint 1 第 10 步**
12. **README + session note**（sprint 1 末尾）

每步独立 commit，方便 revert。

## 12. 后续

- v1.7 候选：`*_from_array` 改 `*_arr` 命名（与 Rust 风格一致）
- v1.7 候选：把 `_from_array` 提到公共位置（`book_cut.utils.image`）
- v1.7 候选：A1 + B1（流式 pipeline）联动 —— 1000+ 页省更多
- v2 候选：cv2.warpAffine 改 GPU（Metal/CUDA）—— 旋转 stage 5x 提速
- v2 候选：numpy → cupy 路径（仅在 CUDA 可用时启用）
