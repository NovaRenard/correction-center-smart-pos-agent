"""A process-level lock for the tray application."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class SingleInstance:
    """QLockFile-based protection for one GUI/runtime per local data directory."""

    def __init__(self, data_directory: Path) -> None:
        data_directory.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(data_directory / "desktop.lock"))
        self._lock.setStaleLockTime(0)

    def acquire(self) -> bool:
        return self._lock.tryLock(100)

    def release(self) -> None:
        if self._lock.isLocked():
            self._lock.unlock()
