from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from hexharness.events.types import Event

Subscriber = Callable[[Event], Awaitable[None] | None]


class EventBus:
    """In-process async pub/sub. Subscribers are fire-and-forget; a slow or failing
    subscriber must never block the append that produced the event."""

    def __init__(self) -> None:
        self._subs: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subs.append(fn)

    async def publish(self, event: Event) -> None:
        for fn in self._subs:
            try:
                result = fn(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 — a bad subscriber can't break the stream
                # ponytail: swallow-and-continue; add structured sub-error logging when observability lands
                pass
