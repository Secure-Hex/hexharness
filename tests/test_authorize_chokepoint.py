"""Invariant #1: the loop never runs a tool except through authorize()->ALLOW.
Invariant: fail-closed — unknown/unclassified tool is denied."""
from __future__ import annotations

from hexharness.agent.loop import AgentLoop
from hexharness.control.hitl import DenyAllApprover
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.events.types import EventType
from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, ToolUseBlock, Usage
from hexharness.tools.base import RiskLevel
from hexharness.tools.registry import ToolRegistry

from tests._fakes import SpyTool
from tests.conftest import ctx, make_control


def _tool_use(name, tid="t1"):
    return ModelResponse(content=[ToolUseBlock(id=tid, name=name, input={})],
                         stop_reason=StopReason.TOOL_USE, usage=Usage(input_tokens=1, output_tokens=1))


def _final(text="done"):
    return ModelResponse(content=[TextBlock(text=text)], stop_reason=StopReason.END_TURN)


async def test_intrusive_denied_and_never_executed():
    cp, events = make_control(approver=DenyAllApprover())
    spy = SpyTool("exploit", RiskLevel.INTRUSIVE)
    reg = ToolRegistry(); reg.register(spy)
    provider = FakeProvider([_tool_use("exploit"), _final("I was blocked")])

    loop = AgentLoop(provider=provider, control=cp, registry=reg, events=events,
                     ctx=ctx(Mode(autonomy=Autonomy.INTERACTIVE, phase=Phase.EXPLOITATION)))
    out = await loop.run("try it")

    assert spy.ran is False  # the invariant: denied => never executed
    assert out == "I was blocked"
    effects = [e.payload["effect"] for e in events.all() if e.type is EventType.AUTHORIZE_DECISION]
    assert effects == ["deny"]


async def test_passive_allowed_and_executed():
    cp, events = make_control()
    spy = SpyTool("lookup", RiskLevel.PASSIVE)
    reg = ToolRegistry(); reg.register(spy)
    provider = FakeProvider([_tool_use("lookup"), _final("ok")])

    loop = AgentLoop(provider=provider, control=cp, registry=reg, events=events,
                     ctx=ctx(Mode(autonomy=Autonomy.INTERACTIVE, phase=Phase.RECON)))
    out = await loop.run("look it up")

    assert spy.ran is True
    assert out == "ok"


async def test_unknown_tool_fail_closed():
    cp, events = make_control()
    reg = ToolRegistry()  # empty
    provider = FakeProvider([_tool_use("ghost"), _final("handled")])

    loop = AgentLoop(provider=provider, control=cp, registry=reg, events=events, ctx=ctx(Mode()))
    out = await loop.run("call a ghost")

    assert out == "handled"
    # no tool ever started
    assert not [e for e in events.all() if e.type is EventType.TOOL_STARTED]
