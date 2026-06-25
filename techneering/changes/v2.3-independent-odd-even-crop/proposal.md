# v2.3 手动裁切独立奇偶页（替代 mirror_even 镜像）

## 背景

v2.2 引入 `--crop manual` 兜底工具，使用单一 `ManualCropProfile` + `mirror_even=True`
让偶页自动 inner↔outer 互换。

**实测问题**：镜像假设"奇偶页物理对称"，但实际古籍常出现：
- 中缝鱼尾形态不对称（奇页黑鱼尾、偶页白鱼尾）
- 版心相对边距不同（偶页页码更靠外）
- 版框残缺程度差异（奇页内框完整、偶页外框撕裂）

强行镜像 = 偶页裁切错位。

## 目标

奇数页归奇数页裁剪，偶数页归偶数页裁剪，两者独立。

## 范围

- `book_cut.detect.manual.ManualCropProfile` 字段替换：4 padding → `odd_page` + `even_page` 两个 `PageCropProfile`
- JSON preset 兼容 v1（mirror_even=True 自动迁移）+ 新 v2 schema
- `apply_manual_crop` 简化（按 `is_even` 选 profile）
- CLI 新增 `--manual-even-padding`，废弃 `--manual-mirror-even`
- GUI Manual Crop 面板分两行（奇页 / 偶页），各 4 Spinbox + 各拖框按钮

## 非目标

- 不改 orchestrator 主循环（`is_even=(i==0)` 已正确）
- 不改 split / binarize 流水线
- 不改 CropCanvas（已支持 `set_is_even()` 切换）