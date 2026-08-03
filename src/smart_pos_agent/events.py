"""Small, optional core event hooks used by non-core adapters such as the desktop app."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

StatusObserver = Callable[[str, Mapping[str, Any]], None]
logger = logging.getLogger(__name__)


def notify(observer: StatusObserver | None, event: str, payload: Mapping[str, Any]) -> None:
    """Call an observer without allowing UI/telemetry code to break POS processing."""
    if observer is not None:
        try:
            observer(event, payload)
        except Exception as exc:  # Defensive boundary around optional adapter code.
            logger.warning(
                "status_observer_failed event=%s class=%s", event, exc.__class__.__name__
            )
