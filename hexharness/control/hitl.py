"""Human-in-the-loop gate. Resolves ASK decisions and requires_approval tools.

Default is fail-closed (deny). The engine injects a concrete approver: CLI prompt for
interactive use, a callback for the daemon/WS transport (phase 6), auto-approve only
inside an explicitly authorized BYPASS/AUTO flow.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class Approver(Protocol):
    async def confirm(self, *, tool: str, risk: str, target: str | None, reason: str) -> bool: ...


class DenyAllApprover:
    """Fail-closed default: nothing is approved unless a real approver is wired in."""

    async def confirm(self, *, tool: str, risk: str, target: str | None, reason: str) -> bool:
        return False


class CallbackApprover:
    def __init__(self, fn: Callable[..., Awaitable[bool] | bool]):
        self._fn = fn

    async def confirm(self, *, tool: str, risk: str, target: str | None, reason: str) -> bool:
        import asyncio

        r = self._fn(tool=tool, risk=risk, target=target, reason=reason)
        return await r if asyncio.iscoroutine(r) else bool(r)


class CLIApprover:
    async def confirm(self, *, tool: str, risk: str, target: str | None, reason: str) -> bool:
        prompt = f"[HITL] approve {tool} (risk={risk}, target={target}) — {reason}? [y/N] "
        try:
            return input(prompt).strip().lower() in ("y", "yes")
        except EOFError:
            return False  # no tty => fail-closed
