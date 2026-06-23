# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：book-cut macOS .app 打包。

使用：
    pyinstaller "packaging/Book Cut.spec"
或通过 build_macos.sh 自动调用。
"""

from pathlib import Path

# 收集 tkinter 的所有资源（macOS 上 Tcl/Tk 框架经常漏打包）
from PyInstaller.utils.hooks import collect_all

tcltk_datas, tcltk_binaries, tcltk_hiddenimports = collect_all("tkinter")
tcltk2_datas, tcltk2_binaries, tcltk2_hiddenimports = collect_all("_tkinter")

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ENTRY = PROJECT_ROOT / "packaging" / "launch_gui.py"


a = Analysis(
    [str(ENTRY)],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=tcltk_binaries + tcltk2_binaries,
    datas=tcltk_datas + tcltk2_datas,
    hiddenimports=tcltk_hiddenimports
    + tcltk2_hiddenimports
    + [
        "book_cut",
        "book_cut.cli",
        "book_cut.gui",
        # v1.6+ C3：pipeline 拆包，必须显式列子模块
        "book_cut.pipeline",
        "book_cut.pipeline.orchestrator",
        "book_cut.pipeline.outline",
        "book_cut.pipeline.crop_config",
        # v1.8+ dry-run：新增 preview + dry_run 模块
        "book_cut.pipeline.preview",
        "book_cut.pipeline.dry_run",
        "book_cut.io.loader",
        "book_cut.io.exporter",
        # v1.7：PDF 页面统一尺寸模块
        "book_cut.io.page_size",
        "book_cut.split.half",
        "book_cut.split.gutter",
        "book_cut.split.border",
        # v1.6+ C2：detect 抽 _utils 共享 helper
        "book_cut.detect._utils",
        "book_cut.detect.trim",
        "book_cut.detect.border",
        "book_cut.detect.single_page",
        "book_cut.detect.paper",
        "book_cut.preprocess.binarize",
        "book_cut.preprocess.deskew",
        "pypdf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 显式排除的大件不影响功能，但能缩 .app 体积
        "matplotlib",
        "pandas",
        "scipy",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "wx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Book Cut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 模式，无 terminal
    disable_windowed_traceback=False,
    target_arch=None,  # 让 --target-architecture 决定（arm64）
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Book Cut",
)

app = BUNDLE(
    coll,
    name="Book Cut.app",
    icon=None,  # 无自定义图标；用户可后续提供 .icns
    bundle_identifier="com.bookcut.app",
    info_plist={
        "CFBundleName": "Book Cut",
        "CFBundleDisplayName": "Book Cut",
        "CFBundleShortVersionString": "0.1.11",
        "CFBundleVersion": "0.1.11",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHumanReadableCopyright": "MIT",
    },
)
