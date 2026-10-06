"""Rules of Engagement. Invariant #4: ROE defines max_mode of the engagement,
IMMUTABLE at runtime. The active mode is min(requested, ROE ceiling). ROE also caps
the final decision by risk and by time window — it can only tighten, never loosen."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time

from hexharness.control.decision import Decision, Effect
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.tools.base import RiskLevel


@dataclass(frozen=True)
class TimeWindow:
    start: time
    end: time

    def contains(self, now: time) -> bool:
        if self.start <= self.end:
            return self.start <= now <= self.end
        return now >= self.start or now <= self.end  # wraps midnight


@dataclass(frozen=True)
class ROE:
    max_risk: RiskLevel = RiskLevel.ACTIVE
    max_autonomy: Autonomy = Autonomy.INTERACTIVE
    max_phase: Phase = Phase.ENUMERATION
    windows: tuple[TimeWindow, ...] = field(default_factory=tuple)

    def clamp_mode(self, requested: Mode) -> Mode:
        """active mode = min(requested, ROE ceiling), on both axes."""
        return Mode(
            autonomy=Autonomy(min(requested.autonomy, self.max_autonomy)),
            phase=Phase(min(requested.phase, self.max_phase)),
        )

    def in_window(self, now: datetime | None = None) -> bool:
        if not self.windows:
            return True
        t = (now or datetime.now()).time()
        return any(w.contains(t) for w in self.windows)

    def cap(self, decision: Decision, risk: RiskLevel, *, now: datetime | None = None) -> Decision:
        if risk > self.max_risk:
            return Decision.deny("roe", f"risk {risk.name} over ROE ceiling {self.max_risk.name}")
        if decision.effect is not Effect.DENY and not self.in_window(now):
            return Decision.deny("roe", "outside engagement time window")
        return decision
