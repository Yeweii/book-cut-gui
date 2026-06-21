#!/usr/bin/env bash
# book-cut macOS .app 一键打包脚本
#
# 用法（在项目根目录）：
#   bash packaging/build_macos.sh
#
# 产物：dist/Book Cut.app（约 200MB，双击启动 GUI）
# 注意：仅构建当前架构（Apple Silicon / arm64）。要给 Intel Mac 用，
#      在 Intel Mac 上重跑本脚本即可。

set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
echo "==> 项目根：$PROJECT_ROOT"

# 1. 准备 venv
if [ ! -d .venv ]; then
    echo "==> 创建 venv"
    python3.11 -m venv .venv
fi

# 2. 安装依赖
echo "==> 安装项目 + pyinstaller"
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet
.venv/bin/pip install -e ".[dev]" --quiet
.venv/bin/pip install pyinstaller --quiet

# 3. 清理旧的构建产物
echo "==> 清理 build/ dist/"
rm -rf build dist

# 4. PyInstaller 打包
echo "==> PyInstaller 打包（arm64）"
.venv/bin/pyinstaller \
    --noconfirm \
    --clean \
    "packaging/Book Cut.spec"

# 5. 验证
APP="dist/Book Cut.app"
if [ ! -d "$APP" ]; then
    echo "❌ 打包失败：$APP 不存在"
    exit 1
fi

echo ""
echo "✅ 打包完成"
echo "   路径：$APP"
echo "   大小：$(du -sh "$APP" | cut -f1)"
echo "   架构：$(file "$APP/Contents/MacOS/Book Cut" | cut -d: -f2)"
echo ""
echo "运行：open \"$APP\""
echo "或拷贝到 Applications：cp -R \"$APP\" /Applications/"
