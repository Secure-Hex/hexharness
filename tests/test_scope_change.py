"""Runtime scope change: model proposes (ENGAGEMENT_PROPOSED), operator approves via
apply_engagement (SCOPE_CHANGED). The model never activates — only apply_engagement does."""
from __future__ import annotations

from pathlib import Path

from hexharness.engagement import Engagement
from hexharness.engagement_builder import EngagementSpec, write_engagement
from hexharness.engine import Engine
from hexharness.events.store import EventStore
from hexharness.tools.native.engagement_tools import EngagementDraftTool

ENG = Path(__file__).resolve().parent.parent / "engagements" / "example.engagement.yaml"


async def test_draft_tool_emits_proposed(tmp_path):
    events = EventStore(":memory:")
    tool = EngagementDraftTool(tmp_path, events=events)
    await tool.run({"name": "newscope", "scope": {"domains": ["beta.example"]}})
    kinds = [e.type.value for e in events.all()]
    assert "engagement.proposed" in kinds
    payload = next(e.payload for e in events.all() if e.type.value == "engagement.proposed")
    assert payload["name"] == "newscope" and payload["path"].endswith(".engagement.yaml")


async def test_apply_engagement_swaps_scope_and_audits(tmp_path):
    engine = Engine.from_engagement(ENG, provider=None)
    assert engine.control.scope_guard.in_scope("www.acme.example") is True
    assert engine.control.scope_guard.in_scope("beta.other.example") is False

    newp = write_engagement(
        EngagementSpec.model_validate({"name": "pivot", "scope": {"domains": ["other.example", "*.other.example"]},
                                       "roe": {"max_risk": "passive"}}),
        tmp_path,
    )
    await engine.apply_engagement(Engagement.load(newp), approved_by="operator")

    # scope now reflects the new engagement, live on the same control plane
    assert engine.control.scope_guard.in_scope("beta.other.example") is True
    assert engine.control.scope_guard.in_scope("www.acme.example") is False
    assert engine.engagement.name == "pivot"
    changed = [e for e in engine.events.all() if e.type.value == "control.scope_changed"]
    assert changed and changed[-1].payload["approved_by"] == "operator"
