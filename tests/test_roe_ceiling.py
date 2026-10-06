"""Invariant #4: ROE defines max_mode; active mode = min(requested, ROE ceiling).
ROE also caps the decision by risk and by time window — it can only tighten."""
from __future__ import annotations

from datetime import datetime, time

from hexharness.control.decision import Decision, Effect
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.roe import ROE, TimeWindow
from hexharness.tools.base import RiskLevel

from tests._fakes import SpyTool
from tests.conftest import ctx, make_control


def test_clamp_mode_is_min_on_both_axes():
    roe = ROE(max_autonomy=Autonomy.AUTO, max_phase=Phase.ENUMERATION)
    clamped = roe.clamp_mode(Mode(autonomy=Autonomy.BYPASS, phase=Phase.POST_EXPLOITATION))
    assert clamped.autonomy is Autonomy.AUTO
    assert clamped.phase is Phase.ENUMERATION


def test_clamp_does_not_raise_mode():
    roe = ROE(max_autonomy=Autonomy.BYPASS, max_phase=Phase.POST_EXPLOITATION)
    clamped = roe.clamp_mode(Mode(autonomy=Autonomy.PLAN, phase=Phase.RECON))
    assert clamped.autonomy is Autonomy.PLAN  # min keeps the lower requested value


def test_cap_denies_risk_over_ceiling():
    roe = ROE(max_risk=RiskLevel.ACTIVE)
    capped = roe.cap(Decision.allow("mode"), RiskLevel.INTRUSIVE)
    assert capped.effect is Effect.DENY
    assert capped.gate == "roe"


def test_cap_denies_outside_window():
    roe = ROE(max_risk=RiskLevel.DESTRUCTIVE, windows=(TimeWindow(time(9), time(18)),))
    midnight = datetime(2026, 1, 1, 2, 0)
    capped = roe.cap(Decision.allow("mode"), RiskLevel.PASSIVE, now=midnight)
    assert capped.effect is Effect.DENY


async def test_roe_ceiling_enforced_through_authorize():
    # Engine ROE allows up to DESTRUCTIVE in conftest; override to ACTIVE here.
    cp, _ = make_control(roe=ROE(max_risk=RiskLevel.ACTIVE, max_autonomy=Autonomy.BYPASS,
                                 max_phase=Phase.POST_EXPLOITATION))
    tool = SpyTool("exploit", RiskLevel.INTRUSIVE)
    d = await cp.authorize(ctx(Mode(autonomy=Autonomy.BYPASS, phase=Phase.POST_EXPLOITATION)), tool, {})
    assert d.effect is Effect.DENY
    assert d.gate == "roe"
