"""Phase.BYPASS lifts the phase ceiling (any tool runs regardless of phase), but ROE
max_risk and the Scope Guard still bind."""
from __future__ import annotations

from hexharness.control.decision import Effect
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.roe import ROE
from hexharness.control.scope_guard import Scope
from hexharness.tools.base import RiskLevel

from tests._fakes import SpyTool
from tests.conftest import ctx, make_control

BYPASS = Mode(autonomy=Autonomy.BYPASS, phase=Phase.BYPASS)


def test_phase_bypass_allows_any_risk_at_mode_level():
    # mode.decide no longer denies a destructive tool on phase grounds in BYPASS
    d = BYPASS.decide(RiskLevel.DESTRUCTIVE)
    assert d.effect is Effect.ALLOW


async def test_roe_still_caps_in_phase_bypass():
    # ROE max_risk ACTIVE must still deny an intrusive tool even in phase BYPASS
    cp, _ = make_control(roe=ROE(max_risk=RiskLevel.ACTIVE, max_autonomy=Autonomy.BYPASS,
                                 max_phase=Phase.BYPASS))
    d = await cp.authorize(ctx(BYPASS), SpyTool("exploit", RiskLevel.INTRUSIVE), {})
    assert d.effect is Effect.DENY and d.gate == "roe"


async def test_scope_still_hard_in_phase_bypass():
    cp, _ = make_control(scope=Scope(domains=("acme.example",)),
                         roe=ROE(max_risk=RiskLevel.DESTRUCTIVE, max_autonomy=Autonomy.BYPASS,
                                 max_phase=Phase.BYPASS))
    tool = SpyTool("dns", RiskLevel.ACTIVE, scope_sensitive=True, target_field="host")
    d = await cp.authorize(ctx(BYPASS), tool, {"host": "evil.example"})
    assert d.effect is Effect.DENY and d.gate == "scope_guard"
