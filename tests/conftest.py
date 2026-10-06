from __future__ import annotations

from hexharness.agent.context import ExecContext
from hexharness.control.budget import Budget
from hexharness.control.plane import ControlPlane
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.roe import ROE
from hexharness.control.scope_guard import Scope, ScopeGuard
from hexharness.events.store import EventStore
from hexharness.tools.base import RiskLevel


def make_control(*, scope: Scope | None = None, roe: ROE | None = None, approver=None,
                 budget: Budget | None = None) -> tuple[ControlPlane, EventStore]:
    events = EventStore(":memory:")
    cp = ControlPlane(
        scope_guard=ScopeGuard.from_scope(scope or Scope(domains=("example",), cidrs=("10.0.0.0/8",))),
        roe=roe or ROE(max_risk=RiskLevel.DESTRUCTIVE, max_autonomy=Autonomy.BYPASS,
                       max_phase=Phase.POST_EXPLOITATION),
        budget=budget or Budget(),
        events=events,
        approver=approver,
    )
    return cp, events


def ctx(mode: Mode) -> ExecContext:
    return ExecContext(engagement_id="t", subagent_id="s", mode=mode)
