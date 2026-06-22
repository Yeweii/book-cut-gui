# CHANGELOG

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