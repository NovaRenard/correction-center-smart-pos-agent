# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir specification for the diagnostic CLI."""

from pathlib import Path

PROJECT_ROOT = Path(SPEC).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "smart_pos_agent"

a = Analysis(
    [str(PACKAGE_ROOT / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="KoshakanSmartPosAgentCli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KoshakanSmartPosAgentCli",
)
