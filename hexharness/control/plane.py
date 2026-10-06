"""ControlPlane.authorize() — THE chokepoint (invariant #1).

The agent loop never calls tool.run() directly; it calls authorize() and only the
executor runs the tool, only on ALLOW. Order is fixed (invariant #2):

    scope_guard(target) -> mode.decide(risk) -> roe.cap(decision)

then budget, then HITL. Every gate is fail-closed: any exception anywhere denies.
Every decision is written to the event log (the Audit Log is a projection of it).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from hexharness.control.budget import Budget
from hexharness.control.decision import Decision, Effect
from hexharness.control.hitl import Approver, DenyAllApprover
from hexharness.control.roe import ROE
from hexharness.control.scope_guard import ScopeGuard
from hexharness.events.store import EventStore
from hexharness.events.types import EventType

if TYPE_CHECKING:
    from hexharness.agent.context import ExecContext
    from hexharness.tools.base import Tool


class ControlPlane:
    def __init__(
        self,
        *,
        scope_guard: ScopeGuard,
        roe: ROE,
        budget: Budget,
        events: EventStore,
        approver: Approver | None = None,
    ):
        self.scope_guard = scope_guard
        self.roe = roe
        self.budget = budget
        self.events = events
        self.approver = approver or DenyAllApprover()

    async def authorize(self, ctx: "ExecContext", tool: "Tool", tool_input: dict) -> Decision:
        target: str | None = None
        try:
            # 1. SCOPE — hard gate. No mode, not even BYPASS, can get past this.
            if tool.scope_sensitive:
                target = tool.extract_target(tool_input)
                if not self.scope_guard.in_scope(target):
                    return await self._audit(
                        ctx, tool, Decision.deny("scope_guard", f"target {target!r} out of scope"), target
                    )

            # 2. MODE decides on risk + autonomy (phase ceiling included).
            decision = ctx.mode.decide(tool.risk_level)

            # 3. ROE caps the decision (risk ceiling + time window). Can only tighten.
            decision = self.roe.cap(decision, tool.risk_level, now=ctx.now)

            # BUDGET — deny if any cap is spent.
            if decision.effect is not Effect.DENY:
                spent = self.budget.exhausted()
                if spent:
                    decision = Decision.deny("budget", spent)

            # HITL — resolve ASK, and always confirm a requires_approval tool.
            needs_human = decision.effect is Effect.ASK or (
                decision.effect is not Effect.DENY and tool.requires_approval
            )
            if needs_human:
                ok = await self.approver.confirm(
                    tool=tool.name,
                    risk=tool.risk_level.name,
                    target=target,
                    reason=decision.reason or "approval required",
                )
                decision = (
                    Decision.allow("hitl", "approved")
                    if ok
                    else Decision.deny("hitl", "not approved by human")
                )

            return await self._audit(ctx, tool, decision, target)
        except Exception as exc:  # noqa: BLE001 — fail-closed is the whole point
            deny = Decision.deny("control_plane", f"fail-closed on error: {exc}")
            try:
                return await self._audit(ctx, tool, deny, target)
            except Exception:  # noqa: BLE001
                return deny

    async def _audit(self, ctx: "ExecContext", tool: "Tool", decision: Decision, target) -> Decision:
        await self.events.append(
            EventType.AUTHORIZE_DECISION,
            {
                "subagent": ctx.subagent_id,
                "engagement": ctx.engagement_id,
                "tool": tool.name,
                "risk": tool.risk_level.name,
                "target": target,
                "mode": {"autonomy": ctx.mode.autonomy.name, "phase": ctx.mode.phase.name},
                "effect": decision.effect.value,
                "gate": decision.gate,
                "reason": decision.reason,
            },
        )
        return decision
