"""Thin async client for the engine daemon.

Knows nothing about engines, control planes, or event stores — only JSON-RPC over a
`Transport`. It does not know or care whether the engine is a local daemon on a unix
socket or a remote one over WSS; it was handed a connected transport and talks to it.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from hexharness.protocol import Methods, Request, is_notification
from hexharness.transport import Transport, TransportClosed


class EngineClient:
    def __init__(self, transport: Transport):
        self._transport = transport
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None

    def start(self) -> None:
        """Begin reading from the transport. Idempotent; call once before use (or let
        the first request start it)."""
        if self._reader is None:
            self._reader = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                msg = await self._transport.recv()
                if is_notification(msg):
                    await self._events.put(msg.get("params") or {})
                else:
                    fut = self._pending.pop(msg.get("id"), None)
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
        except TransportClosed:
            pass
        finally:
            await self._events.put(None)  # sentinel: ends the events() iterator
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(TransportClosed())
            self._pending.clear()

    async def _call(self, method: str, params: dict[str, Any]) -> Any:
        self.start()
        self._next_id += 1
        req_id = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._transport.send(Request(id=req_id, method=method, params=params).model_dump())
        msg = await fut
        if msg.get("error"):
            raise RuntimeError(msg["error"].get("message", "engine error"))
        return msg.get("result")

    # --- session API ---------------------------------------------------------------
    async def create_session(self) -> str:
        return (await self._call(Methods.SESSION_CREATE, {}))["session_id"]

    async def attach(self, session_id: str) -> dict[str, Any]:
        return await self._call(Methods.SESSION_ATTACH, {"session_id": session_id})

    async def resume(self, session_id: str, from_seq: int) -> dict[str, Any]:
        return await self._call(
            Methods.SESSION_RESUME, {"session_id": session_id, "from_seq": from_seq}
        )

    async def run(self, session_id: str, prompt: str) -> str:
        return (await self._call(
            Methods.AGENT_RUN, {"session_id": session_id, "prompt": prompt}
        ))["result"]

    async def kill(self, session_id: str, reason: str = "manual") -> dict[str, Any]:
        return await self._call(
            Methods.KILL_TRIGGER, {"session_id": session_id, "reason": reason}
        )

    # --- pushed events --------------------------------------------------------------
    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over pushed `session.event` params ({session_id, event}).
        Yields live events during a run and replayed events after resume; ends when the
        transport closes."""
        self.start()
        while True:
            item = await self._events.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        await self._transport.close()
        if self._reader is not None:
            # Cancel rather than await: the reader is parked in transport.recv() and our
            # own close() doesn't feed this end's inbox, so awaiting it would deadlock.
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
