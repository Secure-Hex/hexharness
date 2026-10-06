"""Single-agent loop. The orchestrator-worker split (phase 8) composes many of these;
each still routes every tool call through the same chokepoint.

INVARIANT #1 lives here: the only place a tool is executed is `_execute`, and it is
reached only after `control.authorize(...)` returned ALLOW. There is no other path.
"""
from __future__ import annotations

from hexharness.agent.context import ExecContext
from hexharness.control.plane import ControlPlane
from hexharness.control.pricing import usd_cost
from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.providers.base import LLMProvider
from hexharness.providers.types import (
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
)
from hexharness.tools.registry import ToolRegistry

DEFAULT_SYSTEM = (
    "You are a pentesting assistant operating inside HexHarness. Every tool call is "
    "mediated by a control plane that enforces scope, rules of engagement, and human "
    "approval. If a tool is denied, respect it and adapt — do not retry a denied action."
)


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        control: ControlPlane,
        registry: ToolRegistry,
        events: EventStore,
        ctx: ExecContext,
        system: str = DEFAULT_SYSTEM,
        model: str | None = None,
        max_iterations: int = 12,
        kill_switch=None,
        on_text=None,
    ):
        self.provider = provider
        self.control = control
        self.registry = registry
        self.events = events
        self.ctx = ctx
        self.system = system
        self.model = model
        self.max_iterations = max_iterations
        self.kill_switch = kill_switch
        self.on_text = on_text

    async def run(self, user_prompt: str) -> str:
        await self.events.append(EventType.USER_PROMPT, {"text": user_prompt, "subagent": self.ctx.subagent_id})
        messages: list[Message] = [Message.user_text(user_prompt)]

        for _ in range(self.max_iterations):
            if self.kill_switch and self.kill_switch.triggered:
                return f"[killed: {self.kill_switch.reason}]"

            resp = await self.provider.complete(
                messages, tools=self.registry.specs(), system=self.system, model=self.model,
                on_text=self.on_text,
            )
            self.control.budget.add_tokens(resp.usage.total_tokens)
            self.control.budget.add_usd(usd_cost(resp.model or self.model or "", resp.usage))
            await self.events.append(
                EventType.MODEL_RESPONSE,
                {"stop_reason": resp.stop_reason.value, "tokens": resp.usage.total_tokens},
            )
            await self.events.append(
                EventType.BUDGET_UPDATED,
                {"tokens_used": self.control.budget.tokens_used, "usd_used": round(self.control.budget.usd_used, 4)},
            )
            messages.append(Message(role=Role.ASSISTANT, content=resp.content))

            tool_uses = resp.tool_uses()
            if resp.stop_reason is not StopReason.TOOL_USE or not tool_uses:
                return resp.text()

            results: list[ToolResultBlock] = []
            for tu in tool_uses:
                results.append(await self._handle_tool_use(tu))
            messages.append(Message(role=Role.USER, content=results))  # type: ignore[arg-type]

        return "[max iterations reached]"

    async def _handle_tool_use(self, tu) -> ToolResultBlock:
        tool = self.registry.get(tu.name)
        if tool is None:
            # Fail-closed: unknown tool is never executed.
            return ToolResultBlock(tool_use_id=tu.id, content=f"unknown tool: {tu.name}", is_error=True)

        # THE chokepoint. No branch executes the tool without passing here first.
        decision = await self.control.authorize(self.ctx, tool, tu.input)
        if not decision.allowed:
            return ToolResultBlock(
                tool_use_id=tu.id,
                content=f"DENIED by {decision.gate}: {decision.reason}",
                is_error=True,
            )
        return await self._execute(tool, tu)

    async def _execute(self, tool, tu) -> ToolResultBlock:
        await self.events.append(EventType.TOOL_STARTED, {"tool": tool.name, "input": tu.input})
        try:
            output = await tool.run(tu.input)
            await self.events.append(EventType.TOOL_FINISHED, {"tool": tool.name, "ok": True})
            return ToolResultBlock(tool_use_id=tu.id, content=output)
        except Exception as exc:  # noqa: BLE001
            await self.events.append(EventType.TOOL_FINISHED, {"tool": tool.name, "ok": False, "error": str(exc)})
            return ToolResultBlock(tool_use_id=tu.id, content=f"tool error: {exc}", is_error=True)
