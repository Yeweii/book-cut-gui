# v2.4 手动切分线（--split manual，一本书一条 x）

## 背景

当前 `book_cut` 提供三种自动切分策略：`half` / `gutter` / `border`，加上 v1.9.2 的 `none`（不切分）。
实测中遇到三类自动切分都失败的扫描件：

1. **古籍漫漶严重**：中缝墨迹洇开，`gutter` 找不到连续白段
2. **扫描件倾斜 + 中缝模糊**：`border` Hough 找不到版框，`half` 偏离 > 20%
3. **手抄本 / 影印件不规则**：版心位置不固定，自动策略反复猜错

现有 `book_cut/detect/manual.py` 提供「手动裁切」（post-split 4 个 padding），但与"手动选切分线"是**两件事**——
v2.2 至今没有"用户画一条线决定中缝"的能力，必须盲信自动算法或脚本里手算 `--half-offset`。

古籍数字化的常见 workaround 是用 Photoshop 量像素写到脚本里——非常笨拙。

## 目标

新增 `--split manual` 切分策略：用户在 GUI 里对**一张代表性页**画一条垂直中缝线，整本书复用同一条 x。

PDF 输入时，必须先**显性展示** pymupdf 转出来的首页（弹窗），再让用户选线——而不是把 PDF 转换藏在内部。

CLI 端通过 `--pick-split-line` 子命令复用同一弹窗，输出 JSON preset 给主流程用。

## 范围

### 新增
- `src/book_cut/split/manual.py`：`ManualSplitProfile` dataclass（v1 JSON schema）+ `apply_manual_split` 函数
- `src/book_cut/split/__init__.py`：注册 `manual` 策略入口
- `src/book_cut/pipeline/orchestrator.py`：在 `_compute_page` 加 `manual` 分支
- `src/book_cut/cli.py`：
  - `--split` choices 加 `manual`
  - 新增 `--manual-split-x N`（直接传 x）
  - 新增 `--manual-split-preset PATH`（从 JSON 加载）
  - 新增 `--pick-split-line` 子命令（弹 GUI 选线 → 输出 JSON）
- `src/book_cut/gui.py`：
  - 主窗「切分」区 combobox 加 `manual` 选项 + 「选切分线...」按钮
  - 新增 `run_pick_split_line()` 子命令入口
- `src/book_cut/gui_canvas.py` 或新 `src/book_cut/split/picker_ui.py`：
  - 新增 `SplitLinePicker` Toplevel（垂直线 + 手柄 + Spinbox 联动）
- `tests/test_manual_split.py`：~12 用例
- `samples/crop_profiles/v2_manual_split_example.json`：示例 preset
- `CHANGELOG.md`：v2.4 / 0.3.6 条目

### 修改
- `src/book_cut/split/__init__.py` 现有的 `_split_from_array` dispatcher 加 `manual` 分支
- `src/book_cut/pipeline/orchestrator.py:_compute_page` 加 manual split 处理（约 15 行）
- `README.md`：「切分策略」表格 + 「用法」新增手动选线示例
- `CHANGELOG.md`：0.3.6 条目

## 非目标

- **不**改 `--page-order` 默认值（仍是 `ltr`，与 v2.3 一致）
- **不**改 manual crop（`--crop manual`）任何字段——`--split manual` 与 `--crop manual` 正交
- **不**做 per-page override（一本书一条线已满足 95% 场景；per-page 留 v2.5+）
- **不**支持 1:3+ 多页扫描（v2.4 仅 1:2；超出会 warn `MS010`）
- **不**做撤销 / 重做（YAGNI；v1 简化）
- **不**做多页预览切换（仅首页选线；多页验证通过 `--dry-run`）

## 错误码

新增 `MSxxx` 系列（与现有 `BCxxx` 区分）：

| 码 | 触发 | 行为 |
|----|------|------|
| `MS001` | `split_x` 越界（`<1` 或 `>=W`） | fatal |
| `MS002` | `split_x` 不是 int | fatal |
| `MS003` | `source_size` ≠ 当前图 | warn + 继续 |
| `MS004` | 既无 `--manual-split-x` 也无 `--manual-split-preset` | fatal |
| `MS005` | preset 文件不存在 / JSON 解析失败 | fatal |
| `MS006` | preset `version` 未知 | fatal |
| `MS007` | 单页输入 + `--split manual` 启用 | warn + 跳过 manual |
| `MS008` | 输入 0 页 | fatal（exit 2） |
| `MS009` | preset `deskew_applied` 与当前 `--deskew` 状态不一致 | fatal |
| `MS010` | 跨页输入（sub_arrs 长 >2）暂不支持 | warn + 用首条线切前两张 |

## 影响面

### 用户
- **古籍党**：能精确控制中缝 x，不再被自动算法坑
- **现代点校本**：影响小（gutter 通常够用）
- **CLI 自动化**：可写 `--pick-split-line -i book.pdf -o preset.json` 复用

### 代码
- 1 个新模块（`src/book_cut/split/manual.py`，~150 行）
- 1 个新 UI 类（`SplitLinePicker`，~200 行）
- orchestrator 加 ~15 行
- CLI 加 ~80 行
- GUI 主窗加 ~40 行
- 测试 ~200 行

### 性能
- 选线 sub-command 仅转换首页 + 一次 GUI 弹窗，O(1)
- 主流程 manual split 等价于 `arr[:, :sx]` + `arr[:, sx:]`，与 `half` 一样 O(W·H)，无额外开销

## 风险

| 风险 | 缓解 |
|------|------|
| 与 `--split manual` 同名导致 CLI/GUI 混淆 | GUI 显示完整中文「手动（画线）」，CLI `--help` 描述详细 |
| 用户选线时 deskew 状态与跑时不一致导致错位 | `MS009` 强约束；preset 必带 `deskew_applied`，主流程校验 |
| `auto_single_page=True` 检测为单页时与 manual 冲突 | `MS007` warn + 跳过；不让用户困惑"为什么 manual 没切" |
| 1:3+ 跨页输入 | `MS010` warn 告知 v2.4 不支持，避免静默错误 |
| 跨书复用 preset（source_size 不匹配） | `MS003` warn + 继续；split_x 是绝对像素，跨书必须重选 |
