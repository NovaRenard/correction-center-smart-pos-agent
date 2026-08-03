"""Deduplicated, user-facing tray notifications."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class NotificationDeduplicator:
    cooldown_seconds: float = 30.0
    _last_seen: dict[str, float] = field(default_factory=dict)

    def should_show(self, key: str, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        previous = self._last_seen.get(key)
        if previous is not None and moment - previous < self.cooldown_seconds:
            return False
        self._last_seen[key] = moment
        return True
