# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Margin Mate
# Build with:  pyinstaller margin_mate.spec --clean

import sys
import os

block_cipher = None

if sys.platform == "darwin":
    icon = "icon.icns" if os.path.exists("icon.icns") else None
elif sys.platform == "win32":
    icon = "icon.ico" if os.path.exists("icon.ico") else None
else:
    icon = None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates",           "templates"),
        ("static",              "static"),
        ("config.example.json", "."),
    ],
    hiddenimports=[
        # APScheduler
        "apscheduler.schedulers.background",
        "apscheduler.executors.pool",
        # pywebview backends
        "webview.platforms.cocoa",      # macOS
        "webview.platforms.winforms",   # Windows
        "webview.platforms.gtk",        # Linux
        # lxml / bs4
        "lxml.etree",
        "lxml._elementpath",
        "bs4",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PySide6", "PySide2", "PyQt6"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir mode — no unpacking on every launch, opens much faster
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MarginMate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MarginMate",
)

# macOS — wrap in a .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MarginMate.app",
        icon=icon,
        bundle_identifier="com.marginmate.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
