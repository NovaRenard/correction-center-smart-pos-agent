from __future__ import annotations

import random
import secrets


class ExponentialBackoff:
    def __init__(
        self, minimum: float, maximum: float, random_source: random.Random | None = None
    ) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self._random = random_source or secrets.SystemRandom()
        self._attempt = 0

    def reset(self) -> None:
        self._attempt = 0

    def next_delay(self) -> float:
        base = min(self.maximum, self.minimum * (2**self._attempt))
        self._attempt += 1
        return float(base * self._random.uniform(0.8, 1.2))
