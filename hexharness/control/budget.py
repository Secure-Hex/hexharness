from __future__ import annotations

import time as _time
from dataclasses import dataclass, field


@dataclass
class Budget:
    """Tracks spend against hard caps. Any cap of 0/None means unlimited for that axis."""

    max_tokens: int | None = None
    max_usd: float | None = None
    max_seconds: float | None = None

    tokens_used: int = 0
    usd_used: float = 0.0
    _started: float = field(default_factory=_time.monotonic)

    def add_tokens(self, n: int) -> None:
        self.tokens_used += n

    def add_usd(self, amount: float) -> None:
        self.usd_used += amount

    def elapsed(self) -> float:
        return _time.monotonic() - self._started

    def exhausted(self) -> str | None:
        """Return the name of the first exceeded cap, else None. Fail-closed is the
        caller's job: treat any non-None as a hard deny."""
        if self.max_tokens and self.tokens_used >= self.max_tokens:
            return f"token budget ({self.tokens_used}/{self.max_tokens})"
        if self.max_usd and self.usd_used >= self.max_usd:
            return f"usd budget ({self.usd_used:.2f}/{self.max_usd:.2f})"
        if self.max_seconds and self.elapsed() >= self.max_seconds:
            return f"time budget ({self.elapsed():.0f}s/{self.max_seconds:.0f}s)"
        return None
