"""Natural-language -> engagement.yaml drafting. The agent can draft but never
self-activate: the bootstrap engine can only draft, not scan (invariants #3/#4)."""
from __future__ import annotations

import pytest

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engagement import Engagement
from hexharness.engagement_builder import EngagementSpec, render_yaml, write_engagement
from hexharness.engine import Engine
from hexharness.tools.base import RiskLevel
from hexharness.tools.native import EngagementDraftTool

from tests._fakes import SpyTool
from tests.conftest import ctx


def _spec() -> EngagementSpec:
    return EngagementSpec.model_validate({
        "name": "acme test",
        "client": "ACME",
        "scope": {"domains": ["acme.example"], "cidrs": ["203.0.113.0/24"],
                  "exclusions": ["vpn.acme.example"]},
        "roe": {"max_risk": "active", "max_autonomy": "interactive", "max_phase": "enumeration"},
    })


def test_render_roundtrips_through_engagement(tmp_path):
    path = write_engagement(_spec(), tmp_path)
    eng = Engagement.load(path)                 # must parse as a real engagement
    guard = eng.scope_guard()
    assert guard.in_scope("www.acme.example") is True
    assert guard.in_scope("vpn.acme.example") is False
    assert eng.roe_policy().max_risk is RiskLevel.ACTIVE


def test_invalid_cidr_raises_before_write():
    bad = EngagementSpec.model_validate({"name": "x", "scope": {"cidrs": ["not-a-cidr"]}})
    with pytest.raises(Exception):
        render_yaml(bad)


def test_unknown_enum_raises():
    bad = EngagementSpec.model_validate({"name": "x", "roe": {"max_risk": "nuclear"}})
    with pytest.raises(Exception):
        render_yaml(bad)


async def test_draft_tool_writes_and_returns_yaml(tmp_path):
    tool = EngagementDraftTool(tmp_path)
    out = await tool.run(_spec().model_dump())
    assert "NOT yet active" in out
    files = list(tmp_path.glob("*.engagement.yaml"))
    assert len(files) == 1 and Engagement.load(files[0]).name == "acme test"


async def test_bootstrap_can_draft_but_not_scan():
    boot = Engine.bootstrap()
    names = [s.name for s in boot.registry.specs()]
    assert names == ["engagement_draft"]  # no scanners exposed during bootstrap

    # Even if some ACTIVE tool were attempted, bootstrap's report-only/passive ceiling denies it.
    d = await boot.control.authorize(
        ctx(Mode(autonomy=Autonomy.REPORT, phase=Phase.RECON)),
        SpyTool("dns", RiskLevel.ACTIVE), {},
    )
    assert d.effect.value == "deny"
