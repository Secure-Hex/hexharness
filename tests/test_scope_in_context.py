"""The model's system prompt carries the live engagement scope + ROE + mode."""
from __future__ import annotations

from hexharness.agent.loop import AgentLoop
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, Usage
from hexharness.tools.registry import ToolRegistry

from tests.conftest import ctx, make_control


def _loop(provider):
    cp, events = make_control()  # scope: domains=example, cidrs=10.0.0.0/8; ROE destructive
    return AgentLoop(provider=provider, control=cp, registry=ToolRegistry(), events=events,
                     ctx=ctx(Mode(Autonomy.BYPASS, Phase.EXPLOITATION)))


def test_system_prompt_includes_scope_roe_mode():
    sysmsg = _loop(FakeProvider([]))._system_with_scope()
    assert "example" in sysmsg and "10.0.0.0/8" in sysmsg
    assert "max_risk=destructive" in sysmsg
    assert "bypass/exploitation" in sysmsg
    assert "auto-denied" in sysmsg.lower() or "ENFORCED" in sysmsg


async def test_run_sends_scope_aware_system():
    prov = FakeProvider([ModelResponse(content=[TextBlock(text="ok")], stop_reason=StopReason.END_TURN,
                                       usage=Usage(input_tokens=1, output_tokens=1))])
    loop = _loop(prov)
    # patch complete to capture the system it receives
    captured = {}
    orig = prov.complete
    async def spy(messages, **kw):
        captured["system"] = kw.get("system")
        return await orig(messages, **kw)
    prov.complete = spy
    await loop.run("do recon")
    assert "In-scope domains: example" in captured["system"]
