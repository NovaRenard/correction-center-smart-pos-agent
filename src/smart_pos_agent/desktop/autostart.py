"""Current-user Windows Task Scheduler integration for the GUI executable."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "Koshakan Smart POS Agent"


def build_enable_command(executable_path: Path) -> list[str]:
    """Build a command that contains only the GUI executable, never credentials or arguments."""
    return [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/TR",
        str(executable_path),
        "/F",
    ]


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(  # noqa: S603
        ["schtasks", "/Query", "/TN", TASK_NAME],  # noqa: S607
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0


def enable(executable_path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("Автозапуск через Task Scheduler доступен только в Windows.")
    resolved = executable_path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Не найден GUI-файл: {resolved}")
    result = subprocess.run(  # noqa: S603
        build_enable_command(resolved), capture_output=True, check=False, text=True
    )
    if result.returncode != 0:
        raise RuntimeError("Не удалось создать задачу автозапуска.")


def disable() -> None:
    if os.name != "nt":
        return
    result = subprocess.run(  # noqa: S603
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],  # noqa: S607
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError("Не удалось удалить задачу автозапуска.")


def current_gui_executable() -> Path:
    """Return the packaged GUI executable; source runs must not register Python by mistake."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Автозапуск доступен после сборки Windows-приложения.")
    return Path(sys.executable).resolve()
