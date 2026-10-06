"""Orchestrator-worker coordination (phase 8, part 2).

The orchestrator LLM plans an objective into a list of ``{role, task}`` subtasks.
Each subtask is handed to a worker that runs its OWN AgentLoop with:

  - an ISOLATED ExecContext (distinct subagent_id, the role's phase),
  - its OWN message history (AgentLoop.run builds a fresh list — workers never
    share messages, that is the context isolation),
  - a registry filtered to the role's tools.

Workers reuse the PARENT control plane, registry source, and event store: every
worker tool call still routes through ControlPlane.authorize with its own ctx —
the orchestrator never bypasses the chokepoint. Results are aggregated and
returned; delegation start/finish is traced on the event log.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from hexharness.agent.context import ExecContext
from hexharness.agent.loop import AgentLoop
from hexharness.agent.subagents import ROLES, Role
from hexharness.control.plane import ControlPlane
from hexharness.control.policy import Autonomy, Mode
from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.providers.base import LLMProvider
from hexharness.tools.registry import ToolRegistry

ORCHESTRATOR_SYSTEM = (
    "You are the lead pentest orchestrator. Decompose the objective into subtasks for "
    "specialist workers. Reply with ONLY a JSON array of objects "
    '{"role": <one of: ' + ", ".join(ROLES) + '>, "task": <imperative instruction>}. '
    "No prose, no code fences."
)


class Orchestrator:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        control: ControlPlane,
        registry: ToolRegistry,
        events: EventStore,
        engagement_id: str,
        model: str | None = None,
        autonomy: Autonomy = Autonomy.INTERACTIVE,
        max_iterations: int = 12,
        kill_switch: Any = None,
        # Per-worker provider. Default: reuse the planning provider. A factory lets a
        # caller (or test) give each worker an independent scripted provider.
        make_worker_provider: Callable[[Role], LLMProvider] | None = None,
    ):
        self.provider = provider
        self.control = control
        self.registry = registry
        self.events = events
        self.engagement_id = engagement_id
        self.model = model
        self.autonomy = autonomy
        self.max_iterations = max_iterations
        self.kill_switch = kill_switch
        self._make_worker_provider = make_worker_provider

    async def run(self, objective: str) -> dict[str, Any]:
        plan = await self._plan(objective)
        workers: list[dict[str, Any]] = []
        for i, item in enumerate(plan):
            workers.append(await self._delegate(ROLES[item["role"]], item["task"], i))
        return {"objective": objective, "plan": plan, "workers": workers}

    async def _plan(self, objective: str) -> list[dict[str, str]]:
        resp = await self.provider.complete(
            [self._user(objective)], system=ORCHESTRATOR_SYSTEM, model=self.model
        )
        self.control.budget.add_tokens(resp.usage.total_tokens)
        return _parse_plan(resp.text())

    async def _delegate(self, role: Role, task: str, i: int) -> dict[str, Any]:
        subagent_id = f"{role.name}-{i}"  # distinct per worker => isolated identity
        # Invariant #4: active mode = min(requested, ROE ceiling) — clamp BOTH axes,
        # not just autonomy, so a role's phase can never exceed the engagement ceiling.
        mode = self.control.roe.clamp_mode(Mode(autonomy=self.autonomy, phase=role.default_phase))
        ctx = ExecContext(engagement_id=self.engagement_id, subagent_id=subagent_id, mode=mode)
        await self.events.append(
            EventType.DELEGATION_STARTED,
            {"subagent": subagent_id, "role": role.name, "phase": mode.phase.name, "task": task},
        )
        loop = AgentLoop(
            provider=self._worker_provider(role),
            control=self.control,  # SHARED chokepoint — authorize runs per worker ctx
            registry=self._filtered_registry(role),
            events=self.events,
            ctx=ctx,
            system=role.system_prompt,
            model=self.model,
            max_iterations=self.max_iterations,
            kill_switch=self.kill_switch,
        )
        result = await loop.run(task)
        await self.events.append(
            EventType.DELEGATION_FINISHED,
            {"subagent": subagent_id, "role": role.name, "result": result},
        )
        return {"role": role.name, "subagent_id": subagent_id,
                "phase": mode.phase.name, "task": task, "result": result}

    def _worker_provider(self, role: Role) -> LLMProvider:
        return self._make_worker_provider(role) if self._make_worker_provider else self.provider

    def _filtered_registry(self, role: Role) -> ToolRegistry:
        reg = ToolRegistry()
        # ponytail: ToolRegistry has no public iterator; read its dict directly.
        for tool in self.registry._tools.values():  # noqa: SLF001
            if role.tool_filter(tool):
                reg.register(tool)
        return reg

    @staticmethod
    def _user(text: str):
        from hexharness.providers.types import Message

        return Message.user_text(text)


def _parse_plan(text: str) -> list[dict[str, str]]:
    """Pull the JSON array out of the model's reply; keep only well-formed, known roles.
    Fail-closed: anything unparseable yields an empty plan (no workers spawned)."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [
        {"role": item["role"], "task": str(item["task"])}
        for item in raw
        if isinstance(item, dict) and item.get("role") in ROLES and item.get("task")
    ]
