"""Locate package data in source trees and PyInstaller onedir builds."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_path(name: str) -> Path:
    """Return an existing desktop resource without relying on the working directory."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if isinstance(bundle_root, str):
        bundled = Path(bundle_root) / "smart_pos_agent" / "resources" / name
        if bundled.exists():
            return bundled
    frozen_root = Path(sys.executable).resolve().parent / "smart_pos_agent" / "resources" / name
    if getattr(sys, "frozen", False) and frozen_root.exists():
        return frozen_root
    return Path(__file__).resolve().parent.parent / "resources" / name
