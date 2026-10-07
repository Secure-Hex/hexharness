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
        on_thinking=None,
        compact_threshold: float = 0.8,
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
        self.on_thinking = on_thinking
        self.compact_threshold = compact_threshold
        # Persistent conversation across run() calls, so the model remembers prior turns
        # and compaction has something to compact.
        self.conversation: list[Message] = []
        self.last_input_tokens = 0

    def _model_id(self) -> str:
        return self.model or getattr(self.provider, "default_model", "") or ""

    def context_ratio(self) -> float:
        """Fraction of the model's context window used by the last call (for the UI)."""
        from hexharness.providers.context_window import usage_ratio

        return usage_ratio(self._model_id(), self.last_input_tokens)

    async def compact(self, *, reason: str = "manual") -> int:
        """Summarize the conversation into durable notes and replace the history with a
        single summary message. Returns how many messages were collapsed."""
        if len(self.conversation) < 2:
            return 0
        before = len(self.conversation)
        summary_req = [
            *self.conversation,
            Message.user_text(
                "Compact this pentest session into terse durable notes: objectives, scope, "
                "confirmed/candidate findings, decisions, and open threads. Preserve facts "
                "needed to continue; drop chatter."
            ),
        ]
        resp = await self.provider.complete(
            summary_req, system="You compact a pentest session transcript into durable notes.",
            model=self.model,
        )
        self.conversation = [Message.user_text(f"[compacted session summary]\n{resp.text()}")]
        self.last_input_tokens = resp.usage.input_tokens
        await self.events.append(
            EventType.CONTEXT_COMPACTED,
            {"reason": reason, "messages_before": before, "messages_after": len(self.conversation)},
        )
        return before - len(self.conversation)

    def _system_with_scope(self) -> str:
        """System prompt + the live engagement boundary (scope, ROE, mode) so the model
        knows where it may act and does not waste turns on auto-denied targets."""
        scope = self.control.scope_guard.scope
        roe = self.control.roe
        lines = [self.system, "", "## Engagement boundary (ENFORCED — out-of-scope or over-ROE actions are auto-denied)"]
        if scope.domains:
            lines.append("In-scope domains: " + ", ".join(scope.domains))
        if scope.cidrs:
            lines.append("In-scope CIDRs: " + ", ".join(scope.cidrs))
        if scope.exclusions:
            lines.append("EXCLUDED (never touch): " + ", ".join(scope.exclusions))
        if not scope.domains and not scope.cidrs:
            lines.append("In-scope targets: (none set — scope-sensitive tools will be denied)")
        lines.append(
            f"ROE ceiling: max_risk={roe.max_risk.name.lower()}, "
            f"max_autonomy={roe.max_autonomy.name.lower()}, max_phase={roe.max_phase.name.lower()}"
        )
        lines.append(
            f"Current mode: {self.ctx.mode.autonomy.name.lower()}/{self.ctx.mode.phase.name.lower()}. "
            "Act only within this scope and ROE; do not attempt targets or risk levels beyond them."
        )
        return "\n".join(lines)

    async def run(self, user_prompt: str) -> str:
        from hexharness.providers.context_window import should_compact

        await self.events.append(EventType.USER_PROMPT, {"text": user_prompt, "subagent": self.ctx.subagent_id})
        # Auto-compact BEFORE adding the new turn if the last call was near the window.
        if should_compact(self._model_id(), self.last_input_tokens, self.compact_threshold):
            await self.compact(reason="auto")
        self.conversation.append(Message.user_text(user_prompt))
        messages = self.conversation
        system = self._system_with_scope()  # rebuilt each turn so scope/ROE changes show up

        for _ in range(self.max_iterations):
            if self.kill_switch and self.kill_switch.triggered:
                return f"[killed: {self.kill_switch.reason}]"

            resp = await self.provider.complete(
                messages, tools=self.registry.specs(), system=system, model=self.model,
                on_text=self.on_text, on_thinking=self.on_thinking,
            )
            self.last_input_tokens = resp.usage.input_tokens
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
