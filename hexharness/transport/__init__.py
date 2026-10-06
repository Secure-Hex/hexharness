"""Transport abstraction: framed JSON message streams.

The client and daemon both talk to a `Transport` and neither hard-codes WebSockets.
`send`/`recv` move whole JSON objects (dicts) — framing is the transport's concern:
WebSockets frame messages natively, and the in-memory pair just hands dicts across a
queue. Swap the transport and the same client/daemon run local (unix socket) or remote
(WSS) unchanged.
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable


class TransportClosed(Exception):
    pass


@runtime_checkable
class Transport(Protocol):
    async def send(self, message: dict[str, Any]) -> None: ...
    async def recv(self) -> dict[str, Any]: ...  # raises TransportClosed when drained/closed
    async def close(self) -> None: ...


class InMemoryTransport:
    """One end of a connected pair. `connected_pair()` returns the two ends wired so
    that each one's sends land in the other's recv queue. For tests — no network."""

    def __init__(self, outbox: asyncio.Queue, inbox: asyncio.Queue):
        self._outbox = outbox
        self._inbox = inbox
        self._closed = False

    @classmethod
    def connected_pair(cls) -> tuple["InMemoryTransport", "InMemoryTransport"]:
        a_to_b: asyncio.Queue = asyncio.Queue()
        b_to_a: asyncio.Queue = asyncio.Queue()
        return cls(a_to_b, b_to_a), cls(b_to_a, a_to_b)

    async def send(self, message: dict[str, Any]) -> None:
        if self._closed:
            raise TransportClosed()
        await self._outbox.put(message)

    async def recv(self) -> dict[str, Any]:
        msg = await self._inbox.get()
        if msg is _CLOSE:
            raise TransportClosed()
        return msg

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._outbox.put(_CLOSE)  # unblock the peer's recv


_CLOSE = object()  # sentinel pushed through the queue to wake a blocked recv


class WebSocketTransport:
    """websockets-backed transport for local (unix socket) or remote (WSS) engines.

    `websockets` is lazy-imported so the daemon/client/test suite import fine without
    it installed — it only loads when you actually open a WS connection. Install it via
    the optional `[daemon]` extra.
    """

    def __init__(self, ws: Any):
        self._ws = ws  # a websockets connection object

    @classmethod
    async def connect(cls, uri: str, **kwargs: Any) -> "WebSocketTransport":
        # ws://, wss://, or unix:// (websockets supports a unix_socket path too).
        try:
            import websockets  # lazy: keeps `websockets` out of the core dep set
        except ModuleNotFoundError as exc:  # pragma: no cover - env without the extra
            raise RuntimeError("install hexharness[daemon] for WebSocketTransport") from exc
        ws = await websockets.connect(uri, **kwargs)
        return cls(ws)

    async def send(self, message: dict[str, Any]) -> None:
        import json
        try:
            await self._ws.send(json.dumps(message, default=str))
        except Exception as exc:  # noqa: BLE001
            raise TransportClosed() from exc

    async def recv(self) -> dict[str, Any]:
        import json
        try:
            raw = await self._ws.recv()
        except Exception as exc:  # noqa: BLE001
            raise TransportClosed() from exc
        return json.loads(raw)

    async def close(self) -> None:
        await self._ws.close()
