"""Out-of-band secret acquisition. When a tool needs a secret the Vault doesn't have,
the control plane asks a SecretRequester — a channel SEPARATE from the agent/model
loop. The operator provides the value (e.g. pastes an API key into a masked prompt);
it goes straight into the Vault and NEVER into a prompt, tool_result, or event payload.
Only the secret's NAME is ever logged.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class SecretRequester(Protocol):
    async def request(self, *, name: str, reason: str) -> str | None:
        """Return the secret value, or None to cancel (fail-closed => the action is denied)."""
        ...


class DenySecretRequester:
    """Default: nothing can be supplied, so a missing secret denies the action."""

    async def request(self, *, name: str, reason: str) -> str | None:
        return None


class CallbackSecretRequester:
    def __init__(self, fn: Callable[..., Awaitable[str | None] | str | None]):
        self._fn = fn

    async def request(self, *, name: str, reason: str) -> str | None:
        import asyncio

        r = self._fn(name=name, reason=reason)
        return await r if asyncio.iscoroutine(r) else r


class GetpassSecretRequester:
    """CLI: read the secret from the terminal without echoing it."""

    async def request(self, *, name: str, reason: str) -> str | None:
        import getpass

        try:
            value = getpass.getpass(f"[secret] {name} needed ({reason}). Paste value (hidden): ")
        except (EOFError, KeyboardInterrupt):
            return None
        return value or None
