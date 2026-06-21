# 2026-06-21 · v1.5 Sprint 3: C1 Hough 公共模块 + A3 联动缓存

## 0. 背景

当前 Hough 直线检测在 3 个模块独立实现：

| 文件 | 函数 | 用途 |
|---|---|---|
| `preprocess/deskew.py:70` | `_detect_angle_hough` | 检测倾斜角度 |
| `split/border.py:21` | `_detect_outer_rectangle` | 找版框矩形 |
| `detect/border.py:32` | `_detect_lines` | 找版框矩形 |

3 处都做：Canny → HoughLinesP → cluster_lines → (verticals, horizontals)
参数略有差异（threshold、minLineLength），但 80% 逻辑相同。

### 重复成本

- **80 LOC 重复代码**：3 处 cluster 函数、3 处 Canny 调用、3 处 HoughLinesP
- **不一致风险**：参数改了一处忘改另一处（如 threshold=60 vs 80）
- **--split border --crop border 联动**：同一张图跑两次 HoughLinesP（~4ms/页）

## 1. 目标

**C1**：抽 `book_cut/detect/_hough.py` 共享模块
**A3**：split_border 与 crop_to_border 联动，第二次复用第一次的 Hough 结果

## 2. 方案候选

### 方案 A：共享模块 + 联动缓存（推荐）

1. 抽 `book_cut/detect/_hough.py`：
   ```python
   def detect_lines(gray, threshold=80, min_length_factor=20, max_gap=10) -> list[tuple[int,int,int,int]]
   def cluster_lines(lines, tol=5) -> tuple[list[int], list[int]]  # (vs, hs)
   def canny_edges(gray, low=50, high=150) -> np.ndarray  # 共享
   ```

2. 3 个 caller 改为薄包装：
   - `_detect_angle_hough(gray)` → 调 `detect_lines` + 自己算角度中位数
   - `_detect_outer_rectangle(gray)` → 调 `detect_lines` + cluster + 取最外侧
   - `_detect_lines(gray)` → 直接用 `detect_lines + cluster_lines`

3. **A3 联动**：split_border_from_array 返回值改为：
   ```python
   def split_border_from_array(arr, return_hough_cache=False):
       ...
       cache = detect_lines(arr, ...)  # 只跑一次
       if not cache:
           return split_half_from_array(arr)  # fallback
       x = (cache.vs[0] + cache.vs[-1]) // 2
       return [arr[:, :x], arr[:, x:]], cache  # 可选返回 cache
   ```

4. crop_to_border_from_array 增加可选参数：
   ```python
   def crop_to_border_from_array(arr, padding=5, config=None, hough_cache=None):
       if hough_cache is not None:
           lines = hough_cache  # 复用
       else:
           lines = detect_lines(arr, ...)
       ...
   ```

5. pipeline 主循环：
   ```python
   sub_arrs, hough_cache = split_border_from_array(arr, return_hough_cache=(
       args.split == "border" and crop_mode == "border"
   ))
   for sub in sub_arrs:
       cropped = crop_to_border_from_array(sub, ..., hough_cache=(
           hough_cache if not _is_subpage(hough_cache, sub) else None
       ))
   ```

**挑战**：split_border 用的 Hough 在整张双页图，crop 在单张子图。**子图的 Hough 是不同的子集**——A3 联动不能简单复用，因为：

- split_border 找的是"双页"的左右版框
- crop_to_border 找的是"单页"的版框（更精细）

**实际**：
- 双页图 → split 切分后左/右子图 → crop 各自找版框
- 双页图 Hough 检测到的"最外侧左右竖线"对子图来说是错的（子图只含左版框或右版框）
- 所以**纯联动不能复用**——除非改用"找全局版框，再 map 到子图"的方式

**真正的联动**：split_border 检测时**同时记下左右版框坐标**；crop_to_border 直接用这个坐标，不再跑 Hough。这等价于把 `_detect_lines` 的结果从子图重新计算换成从全局继承。

但这要求 split_border 把"左版框 rect"和"右版框 rect"都返回，crop_to_border 根据子图是左还是右选择对应的 rect。这是个更大的接口改动。

### 方案 B：只做 C1，不做 A3

抽共享模块，但不动 split+crop 联动（避免大改动）。A3 推迟到 v1.6 重构。

**优点**：小、低风险
**缺点**：--split border --crop border 用户仍跑两次 Hough（~4ms/页）

### 决策

**先做方案 B**（仅 C1）。A3 推迟到 v1.6 重构"split+crop 联动接口"。

理由：
- A3 接口改动较大（split 返回 rect 列表而非 x，crop 接收 rect），属于 API 变更
- v1.5 重点是"不 OOM"和"提速"——C1 已经减 80 LOC + 统一参数
- 真实数据里 --split border --crop border 用户极少（默认 gutter + border crop）

## 3. C1 实施细节

### 3.1 新文件 `book_cut/detect/_hough.py`

```python
"""共享 Hough 直线检测工具。

提供：
- ``canny_edges(gray)``：Canny 边检测
- ``detect_lines(gray, ...)``：Canny + HoughLinesP
- ``cluster_lines(lines)``：合并相邻同向线段

3 个 caller（deskew / split_border / crop_border）共用，统一参数。
"""

import cv2
import numpy as np

DEFAULT_CANNY_LOW = 50
DEFAULT_CANNY_HIGH = 150

# 各 caller 的 Hough 参数 preset
HOUGH_PRESETS = {
    "deskew": dict(threshold=80, min_length_factor=20, max_gap=10),
    "split_border": dict(threshold=80, min_length_factor=20, max_gap=10),
    "crop_border": dict(threshold=60, min_length_factor=30, max_gap=8),
}


def canny_edges(gray: np.ndarray, low: int = 50, high: int = 150) -> np.ndarray:
    return cv2.Canny(gray, low, high)


def detect_lines(
    gray: np.ndarray,
    *,
    threshold: int = 80,
    min_length_factor: int = 20,
    max_gap: int = 10,
) -> list[tuple[int, int, int, int]] | None:
    """返回 Hough 直线列表 ``[(x1,y1,x2,y2), ...]`` 或 None。"""
    edges = canny_edges(gray)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=threshold,
        minLineLength=max(20, gray.shape[1] // min_length_factor),
        maxLineGap=max_gap,
    )
    if lines is None:
        return None
    return [tuple(int(v) for v in line) for line in lines[:, 0]]


def cluster_lines(
    lines: list[tuple[int, int, int, int]],
    tol: int = 5,
) -> tuple[list[int], list[int]]:
    """合并相邻同向线段，返回 (竖线 x 列表, 横线 y 列表)。"""
    verticals: list[int] = []
    horizontals: list[int] = []
    for x1, y1, x2, y2 in lines:
        if abs(x1 - x2) < 3:
            verticals.append((x1 + x2) // 2)
        elif abs(y1 - y2) < 3:
            horizontals.append((y1 + y2) // 2)

    def _cluster(values: list[int], tol: int = tol) -> list[int]:
        if not values:
            return []
        values = sorted(values)
        clusters: list[list[int]] = []
        cur = [values[0]]
        for v in values[1:]:
            if v - cur[-1] <= tol:
                cur.append(v)
            else:
                clusters.append(cur)
                cur = [v]
        clusters.append(cur)
        return [int(np.median(c)) for c in clusters]

    return _cluster(verticals), _cluster(horizontals)
```

### 3.2 3 个 caller 改写

#### `preprocess/deskew.py:_detect_angle_hough`

```python
def _detect_angle_hough(gray: np.ndarray, max_angle: float = 5.0) -> float | None:
    """用 Hough 直线找主角度（接近 0° 的水平线）。返回角度（度）。"""
    from book_cut.detect._hough import detect_lines
    lines = detect_lines(gray, threshold=80, min_length_factor=20, max_gap=10)
    if lines is None:
        return None

    angles: list[float] = []
    for x1, y1, x2, y2 in lines:
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if a < 0:
            a += 180
        if a > 90:
            a -= 180
        if abs(a) <= max_angle:
            angles.append(a)

    if len(angles) < 3:
        return None
    return float(np.median(angles))
```

#### `split/border.py:_detect_outer_rectangle`

```python
def _detect_outer_rectangle(gray: np.ndarray) -> tuple[int, int, int, int] | None:
    from book_cut.detect._hough import cluster_lines, detect_lines
    lines = detect_lines(gray, threshold=80, min_length_factor=20, max_gap=10)
    if lines is None:
        return None
    vs, hs = cluster_lines(lines)
    if len(vs) < 2 or len(hs) < 2:
        return None
    h_img, w_img = gray.shape
    if (vs[-1] - vs[0]) < w_img * 0.3 or (hs[-1] - hs[0]) < h_img * 0.3:
        return None
    return (vs[0], hs[0], vs[-1], hs[-1])
```

#### `detect/border.py:_detect_lines`

```python
def _detect_lines(gray: np.ndarray) -> tuple[list[int], list[int]] | None:
    """返回 (竖线 x 列表, 横线 y 列表)。"""
    from book_cut.detect._hough import cluster_lines, detect_lines as _hough_detect
    lines = _hough_detect(gray, threshold=60, min_length_factor=30, max_gap=8)
    if lines is None:
        return None
    vs, hs = cluster_lines(lines)
    if not vs or not hs:
        return None
    return vs, hs
```

### 3.3 保留旧函数签名（向后兼容）

私有 `_detect_lines` / `_detect_outer_rectangle` / `_detect_angle_hough` 保留同名同位置参数，作为"参数固定 + 调共享模块"的薄包装。
公共 `crop_to_border` / `split_border` / `deskew` 零改动。

## 4. 风险

| 风险 | 严重度 | 缓解 |
|---|---|---|
| Hough 参数微调导致检测结果漂移 | 中 | 保留旧 caller 的硬编码参数（threshold=60/80 等）；不优化只重构 |
| cluster 函数 `tol` 默认值差异（split_border 用 5，crop_border 用 5，deskew 不用） | 低 | 统一 tol=5，与现有行为等价 |
| 测试需验证像素一致（Canny 边图应 bitwise 相同） | 低 | 加 `test_hough_common_matches_inline` 行为对等 |

## 5. 验证

### 5.1 单元测试

- `test_hough_common_canny_edges`：输出与内联调用 bitwise 一致
- `test_hough_common_detect_lines`：3 个 preset 各跑一遍，line 数量 ≥ 旧版
- `test_hough_common_cluster_lines`：相同输入产相同输出
- 现有 89 tests 零修改通过

### 5.2 真实数据回归

- ZHSY 66 页：处理结果与 v1.5 Sprint 2 字节级一致（同一 crop_config、同一输出）
- 茶山集 132 页：同上

## 6. 时间估算

| 阶段 | 时间 |
|---|---|
| 写 `_hough.py` + 改 3 个 caller | 1.5h |
| 加 hough 行为对等 test | 1h |
| 跑全 89 测试 + 真实数据 | 0.5h |
| 文档 + commit | 0.5h |
| **总计** | **~3.5h** |

## 7. 后续

- C1 完成后，统一 Hough 参数文档化（v1.5+）
- A3 联动缓存作为 v1.6 重构候选（split_border 返回 rect 列表 + crop 接 rect）
- Hough 参数自适应（按图片尺寸动态调整）作为 v1.7+ 探索