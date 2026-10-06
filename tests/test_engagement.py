"""The declarative engagement.yaml wires the whole control plane correctly."""
from __future__ import annotations

from pathlib import Path

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engagement import Engagement
from hexharness.tools.base import RiskLevel

ENG = Path(__file__).resolve().parent.parent / "engagements" / "example.engagement.yaml"


def test_loads_and_builds_control_objects():
    eng = Engagement.load(ENG)
    assert eng.name == "acme-external-2026"

    guard = eng.scope_guard()
    assert guard.in_scope("www.acme.example") is True
    assert guard.in_scope("vpn.acme.example") is False       # exclusion
    assert guard.in_scope("203.0.113.5") is True
    assert guard.in_scope("8.8.8.8") is False

    roe = eng.roe_policy()
    assert roe.max_risk is RiskLevel.ACTIVE
    assert roe.max_autonomy is Autonomy.INTERACTIVE


def test_clamp_respects_engagement_ceiling():
    eng = Engagement.load(ENG)
    # Ask for the most permissive mode; ROE must clamp it down.
    clamped = eng.clamp(Mode(autonomy=Autonomy.BYPASS, phase=Phase.POST_EXPLOITATION))
    assert clamped.autonomy is Autonomy.INTERACTIVE
    assert clamped.phase is Phase.ENUMERATION
