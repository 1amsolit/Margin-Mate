# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Margin Mate
# Build with:  pyinstaller margin_mate.spec --clean

import sys

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("templates",          "templates"),
        ("static",             "static"),
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MarginMate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # replace with "icon.icns" / "icon.ico" when you have one
)

# macOS — wrap the exe in a .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="MarginMate.app",
        icon=None,          # replace with "icon.icns" when you have one
        bundle_identifier="com.marginmate.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
