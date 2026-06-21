# book-cut · 打包说明

把 GUI 打成 macOS `.app`，双击即用、无需 Python 环境。

## TL;DR

```bash
bash packaging/build_macos.sh          # ≈ 1-2 分钟
open "dist/Book Cut.app"               # 启动 GUI
```

产物：`dist/Book Cut.app`（约 220 MB，arm64）。

## 前置条件

| 依赖 | 版本 | 校验命令 |
|------|------|---------|
| Python | 3.11.x | `python3.11 --version` |
| macOS | 12+（建议 13+，与 PyInstaller 6 兼容） | `sw_vers` |
| 架构 | arm64（Apple Silicon）或 x86_64（Intel） | `uname -m` |

> **架构**：脚本默认构建当前机器架构。要给 Intel Mac 用，请在 Intel 上重跑。Universal binary 需要 `lipo` 合并两次构建产物，超出 v1 范围。

## 一键脚本做什么

`packaging/build_macos.sh` 步骤：

1. 若 `.venv` 不存在则创建（基于 `python3.11`）
2. 装依赖：`requirements.txt` + `pip install -e ".[dev]"` + `pyinstaller`
3. `rm -rf build dist` 清旧产物
4. `pyinstaller packaging/Book Cut.spec` 打包
5. 打印产物大小 + 架构

## 手动打包（脚本失败时回退方案）

```bash
# 1. venv
python3.11 -m venv .venv
source .venv/bin/activate

# 2. 依赖
pip install -r requirements.txt
pip install -e ".[dev]"
pip install pyinstaller

# 3. 清理 + 打包
rm -rf build dist
pyinstaller --noconfirm --clean "packaging/Book Cut.spec"

# 4. 验证
ls -la "dist/Book Cut.app/Contents/MacOS/Book Cut"
open "dist/Book Cut.app"
```

## 产物结构

```
dist/Book Cut.app/
├── Contents/
│   ├── Info.plist           # CFBundle* 元数据
│   ├── MacOS/
│   │   └── Book Cut         # Mach-O 启动器（embedded bootloader + PYZ）
│   ├── Resources/           # 资源：base_library.zip, cv2/, pymupdf/, *.dylib
│   └── _CodeSignature/      # ad-hoc 签名
```

## 发布新版本时

只改两处：

**1. 升级版本号**（`packaging/Book Cut.spec` 的 `info_plist`）：

```python
info_plist={
    "CFBundleShortVersionString": "0.1.4",   # 改这里
    "CFBundleVersion":          "0.1.4",   # 和这里
    ...
}
```

**2. 若新增了 `book_cut.*` 子模块**，把模块名加进 spec 的 `hiddenimports`：

```python
hiddenimports=[
    ...,
    "book_cut.detect.paper",   # 例：v1.3 加的
    "book_cut.your_new_module",
    ...
],
```

> 不加 hiddenimports 也可能工作（PyInstaller 的静态分析有时能扫到），但显式列出是稳妥做法——尤其是只用 type annotation 引用、运行时才 import 的模块。

## 验证清单

打包后逐项打勾：

```bash
# 1. 存在
ls "dist/Book Cut.app" && echo "✓ 产物存在"

# 2. 架构
file "dist/Book Cut.app/Contents/MacOS/Book Cut"
# 期望：Mach-O 64-bit executable arm64（或 x86_64）

# 3. 体积（>150MB 是正常的，PIL + pymupdf + opencv 都很大）
du -sh "dist/Book Cut.app"
# 期望：≈ 220MB

# 4. 启动（不立刻退出）
open "dist/Book Cut.app" && sleep 4 && pgrep -lf "Book Cut"
# 期望：看到一个 Book Cut 进程在跑

# 5. 自定义模块进了 PYZ（举例 v1.3 paper）
.venv/bin/pyi-archive_viewer build/"Book Cut"/PYZ-00.pyz <<< "X paper" \
  | grep "book_cut.detect.paper"
# 期望：输出形如 `0, 1060273, 2941, 'book_cut.detect.paper'`
```

第 5 项是排查 "在开发环境能跑，打包后 ImportError" 的最快方式。

## 常见问题

### `rm: dist: Directory not empty`

`dist/` 里残留 `.DS_Store` 或之前构建产物。`rm -rf` 正常会处理；遇到这条错误一般是 Finder 索引锁住了文件。

```bash
rm -rfv dist build          # -v 看进度，失败再补一刀
xattr -cr "dist/Book Cut.app"  # 清扩展属性（若之前启动过）
```

### 启动后立刻闪退

大概率是 spec 的 `hiddenimports` 漏了某个动态 import 的模块：

```bash
# 看 stderr
"dist/Book Cut.app/Contents/MacOS/Book Cut" 2>&1 | head -20
# 或从 Console.app 找 Book Cut 崩溃报告
```

把缺失模块加进 spec 的 `hiddenimports`，重跑打包。

### Gatekeeper 拦截（"无法打开，因为来自身份不明的开发者"）

未做 codesign / notarize。两种绕过：

```bash
# 1. 解锁单次
xattr -d com.apple.quarantine "dist/Book Cut.app"

# 2. 右键 → 打开 → 仍要打开（之后双击就顺了）
```

正式分发需 Apple Developer 账号 + `codesign --deep --sign "Developer ID Application: ..."` + `notarytool`。超出 v1 范围。

### 体积太大（>250MB）

主要来自 `cv2`（opencv-python，约 80MB）和 `pymupdf`（约 40MB）。两个都是 split/loader 的硬依赖，没法删。

spec 已 exclude：`matplotlib` / `pandas` / `scipy` / `PyQt*` / `wx`——这些都是 PyInstaller 静态扫描误拉的，确认没用就不进 bundle。

### 想做 Universal Binary

```bash
# 在 arm64 上
bash packaging/build_macos.sh   # 产物：dist-arm64/Book Cut.app

# 在 x86_64 上
bash packaging/build_macos.sh   # 产物：dist-x86_64/Book Cut.app

# 合并两个 Mach-O
lipo -create \
  dist-arm64/Book\ Cut.app/Contents/MacOS/Book\ Cut \
  dist-x86_64/Book\ Cut.app/Contents/MacOS/Book\ Cut \
  -output Book\ Cut-universal

# 替换 + 重签
cp Book\ Cut-universal dist-arm64/Book\ Cut.app/Contents/MacOS/Book\ Cut
codesign --deep --force --sign - dist-arm64/Book\ Cut.app
```

## 相关文件

| 文件 | 作用 |
|------|------|
| `packaging/build_macos.sh` | 一键打包脚本 |
| `packaging/Book Cut.spec` | PyInstaller 规格（hiddenimports + version） |
| `packaging/launch_gui.py` | GUI 启动入口（绕开 CLI argparse） |
| `docs/sessions/2026-06-21-book-cut-v1.2.md` | v1.2 首次打包记录 |
| `docs/sessions/2026-06-21-book-cut-v1.3.md` | v1.3 打包记录（仅补 hiddenimports + 版本号） |
