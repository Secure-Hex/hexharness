"""Modes = presets over authorize(), two orthogonal axes (invariant: modes section).

Autonomy: how much human involvement. Phase: which risk ceiling + intent.
The mode lives on the ExecContext per subagent, not as a global.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from hexharness.control.decision import Decision, Effect
from hexharness.tools.base import RiskLevel


class Autonomy(IntEnum):
    # Ordered least->most permissive so min(requested, ceiling) is meaningful.
    PLAN = 0          # planning only, no execution
    REPORT = 1        # read-only, passive tools for report gathering
    INTERACTIVE = 2   # default: ask before anything active+
    AUTO = 3          # run active unattended, ask before intrusive/destructive
    BYPASS = 4        # run without asking (scope guard STILL applies)


class Phase(IntEnum):
    RECON = 0
    ENUMERATION = 1
    EXPLOITATION = 2
    POST_EXPLOITATION = 3
    REPORTING = 4
    # No phase gate: every tool runs regardless of phase. ROE max_risk and the Scope
    # Guard STILL apply — bypass lifts only the phase ceiling, not the hard gates.
    BYPASS = 5


# Each phase pins the max risk allowed while in it.
_PHASE_CEILING: dict[Phase, RiskLevel] = {
    Phase.RECON: RiskLevel.PASSIVE,
    Phase.ENUMERATION: RiskLevel.ACTIVE,
    Phase.EXPLOITATION: RiskLevel.INTRUSIVE,
    Phase.POST_EXPLOITATION: RiskLevel.DESTRUCTIVE,
    Phase.REPORTING: RiskLevel.PASSIVE,
    Phase.BYPASS: RiskLevel.DESTRUCTIVE,
}


@dataclass(frozen=True)
class Mode:
    autonomy: Autonomy = Autonomy.INTERACTIVE
    phase: Phase = Phase.RECON

    def phase_ceiling(self) -> RiskLevel:
        return _PHASE_CEILING[self.phase]

    def decide(self, risk: RiskLevel) -> Decision:
        # Phase gate first: a tool riskier than the phase allows is denied regardless.
        if risk > self.phase_ceiling():
            return Decision.deny("mode", f"risk {risk.name} exceeds phase {self.phase.name}")

        a = self.autonomy
        if a is Autonomy.PLAN:
            return Decision.deny("mode", "plan mode: no execution")
        if a is Autonomy.REPORT:
            return (Decision.allow("mode", "report: passive ok") if risk == RiskLevel.PASSIVE
                    else Decision.deny("mode", "report mode: passive only"))
        if a is Autonomy.INTERACTIVE:
            return (Decision.allow("mode") if risk == RiskLevel.PASSIVE
                    else Decision.ask("mode", f"interactive: confirm {risk.name}"))
        if a is Autonomy.AUTO:
            return (Decision.allow("mode") if risk <= RiskLevel.ACTIVE
                    else Decision.ask("mode", f"auto: confirm {risk.name}"))
        if a is Autonomy.BYPASS:
            return Decision.allow("mode", "bypass")
        return Decision.deny("mode", "unknown autonomy")  # fail-closed
