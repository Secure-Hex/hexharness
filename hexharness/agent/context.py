from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from hexharness.control.policy import Mode


@dataclass(frozen=True)
class ExecContext:
    """Per-subagent execution context. The mode lives HERE, not as a global — each
    subagent (Recon, WebApp, ...) can run at a different autonomy/phase under the same
    ROE ceiling."""

    engagement_id: str
    subagent_id: str
    mode: Mode
    # Pinned clock for deterministic ROE time-window checks in tests; None = real now.
    now: datetime | None = None
