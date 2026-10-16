"""max_iterations is configurable: honored by the Engagement model, serialized to YAML,
and surfaced in the agent's per-turn system prompt."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from hexharness.agent.loop import AgentLoop
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engagement import Engagement
from hexharness.engagement_builder import EngagementSpec, render_yaml
from hexharness.providers.fake import FakeProvider
from hexharness.tools.registry import ToolRegistry

from tests.conftest import ctx, make_control


def test_engagement_default_and_override():
    assert Engagement(name="x").max_iterations == 12
    assert Engagement.model_validate({"name": "x", "max_iterations": 40}).max_iterations == 40


def test_engagement_rejects_non_positive():
    with pytest.raises(ValidationError):
        Engagement.model_validate({"name": "x", "max_iterations": 0})


def test_render_yaml_emits_max_iterations():
    yaml_text = render_yaml(EngagementSpec(name="x", max_iterations=25))
    assert "max_iterations: 25" in yaml_text


def test_system_prompt_reflects_configured_cap():
    cp, events = make_control()
    loop = AgentLoop(provider=FakeProvider([]), control=cp, registry=ToolRegistry(),
                     events=events, ctx=ctx(Mode(Autonomy.BYPASS, Phase.EXPLOITATION)),
                     max_iterations=3)
    sysmsg = loop._system_with_scope()
    assert "at most 3 tool-call rounds" in sysmsg
