# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir specification for the windowed tray application."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

PROJECT_ROOT = Path(SPEC).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "smart_pos_agent"

datas = collect_data_files("smart_pos_agent", includes=["resources/*"])

a = Analysis(
    [str(PACKAGE_ROOT / "desktop" / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KoshakanSmartPosAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KoshakanSmartPosAgent",
)
