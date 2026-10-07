"""Declarative, versionable engagement.yaml -> runtime control-plane objects.

The engagement file is the single source of the ROE ceiling, scope, time windows and
budget. It is loaded once; the ROE it yields is immutable at runtime (invariant #4).
"""
from __future__ import annotations

from datetime import time
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from hexharness.control.budget import Budget
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.roe import ROE, TimeWindow
from hexharness.control.scope_guard import Scope, ScopeGuard
from hexharness.tools.base import RiskLevel


class _ScopeModel(BaseModel):
    cidrs: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class _WindowModel(BaseModel):
    start: str  # "HH:MM"
    end: str


class _RoeModel(BaseModel):
    max_risk: str = "active"
    max_autonomy: str = "interactive"
    max_phase: str = "enumeration"
    windows: list[_WindowModel] = Field(default_factory=list)


class _BudgetModel(BaseModel):
    max_tokens: int | None = None
    max_usd: float | None = None
    max_seconds: float | None = None


class Engagement(BaseModel):
    name: str
    client: str = ""
    scope: _ScopeModel = Field(default_factory=_ScopeModel)
    roe: _RoeModel = Field(default_factory=_RoeModel)
    budget: _BudgetModel = Field(default_factory=_BudgetModel)
    report_template: str = "default.html.j2"
    sandbox_image: str = "kalilinux/kali-rolling"  # Docker image exec_command runs inside

    @classmethod
    def load(cls, path: str | Path) -> "Engagement":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)

    # --- control-plane builders ---

    def scope_guard(self) -> ScopeGuard:
        return ScopeGuard.from_scope(
            Scope(
                cidrs=tuple(self.scope.cidrs),
                domains=tuple(self.scope.domains),
                exclusions=tuple(self.scope.exclusions),
            )
        )

    def roe_policy(self) -> ROE:
        windows = tuple(
            TimeWindow(start=_parse_time(w.start), end=_parse_time(w.end)) for w in self.roe.windows
        )
        return ROE(
            max_risk=RiskLevel[self.roe.max_risk.upper()],
            max_autonomy=Autonomy[self.roe.max_autonomy.upper()],
            max_phase=Phase[self.roe.max_phase.upper()],
            windows=windows,
        )

    def budget_tracker(self) -> Budget:
        return Budget(
            max_tokens=self.budget.max_tokens,
            max_usd=self.budget.max_usd,
            max_seconds=self.budget.max_seconds,
        )

    def clamp(self, requested: Mode) -> Mode:
        """Active mode = min(requested, ROE ceiling) — invariant #4."""
        return self.roe_policy().clamp_mode(requested)


def _parse_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))
