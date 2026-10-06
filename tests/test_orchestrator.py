"""Orchestrator-worker: context isolation, chokepoint still applies, aggregation.

Scripted FakeProviders stand in for both the orchestrator (planning) and each
worker (its own AgentLoop). No network.
"""
from __future__ import annotations

from hexharness.agent.orchestrator import Orchestrator
from hexharness.control.policy import Autonomy, Phase
from hexharness.events.types import EventType
from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, ToolUseBlock, Usage
from hexharness.tools.base import RiskLevel
from hexharness.tools.registry import ToolRegistry

from tests._fakes import SpyTool
from tests.conftest import make_control


def _text(t: str) -> ModelResponse:
    return ModelResponse(content=[TextBlock(text=t)], stop_reason=StopReason.END_TURN)


def _tool_use(name: str, tid: str = "t1") -> ModelResponse:
    return ModelResponse(
        content=[ToolUseBlock(id=tid, name=name, input={})],
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


_PLAN = '[{"role":"recon","task":"recon task"},{"role":"network","task":"net task"}]'


def _build():
    cp, events = make_control()
    spy = SpyTool("passive_lookup", RiskLevel.PASSIVE)  # not scope-sensitive
    reg = ToolRegistry()
    reg.register(spy)

    orch_provider = FakeProvider([_text(_PLAN)])
    workers = {
        "recon": FakeProvider([_tool_use("passive_lookup"), _text("recon done")]),
        "network": FakeProvider([_text("network done")]),
    }
    orch = Orchestrator(
        provider=orch_provider,
        control=cp,
        registry=reg,
        events=events,
        engagement_id="eng",
        autonomy=Autonomy.INTERACTIVE,
        make_worker_provider=lambda role: workers[role.name],
    )
    return orch, events, spy, workers


async def test_workers_get_isolated_contexts_and_right_phase():
    orch, _events, _spy, workers = _build()
    out = await orch.run("pentest the thing")

    by_role = {w["role"]: w for w in out["workers"]}
    assert by_role["recon"]["phase"] == Phase.RECON.name
    assert by_role["network"]["phase"] == Phase.ENUMERATION.name
    # Distinct subagent identities => isolated ExecContexts.
    assert by_role["recon"]["subagent_id"] != by_role["network"]["subagent_id"]

    # Message isolation: each worker's loop started from ONLY its own task, never
    # the objective or a sibling's task.
    assert workers["recon"].calls[0][0].content[0].text == "recon task"
    assert workers["network"].calls[0][0].content[0].text == "net task"


async def test_worker_tool_call_still_routes_through_authorize():
    orch, events, spy, _workers = _build()
    await orch.run("go")

    assert spy.ran is True  # the passive tool actually executed
    decisions = [e for e in events.all() if e.type is EventType.AUTHORIZE_DECISION]
    # The recon worker's call was authorized under its OWN subagent ctx.
    recon_auth = [e for e in decisions if e.payload["subagent"] == "recon-0"]
    assert len(recon_auth) == 1
    assert recon_auth[0].payload["effect"] == "allow"
    assert recon_auth[0].payload["tool"] == "passive_lookup"


async def test_run_aggregates_per_worker_results():
    orch, events, _spy, _workers = _build()
    out = await orch.run("go")

    results = {w["role"]: w["result"] for w in out["workers"]}
    assert results == {"recon": "recon done", "network": "network done"}
    # Delegation was traced start+finish for each worker.
    started = [e for e in events.all() if e.type is EventType.DELEGATION_STARTED]
    finished = [e for e in events.all() if e.type is EventType.DELEGATION_FINISHED]
    assert len(started) == 2 and len(finished) == 2
