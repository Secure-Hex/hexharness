"""Long-lived engine daemon.

Holds one `Engine` per session and answers JSON-RPC over a `Transport`. One daemon
process can outlive many thin clients: a client disconnects, the engine keeps its event
log, and a reattaching client calls `session.resume(from_seq)` to replay what it missed.

Same binary serves local (unix socket) or remote (WSS) — the transport decides. The
daemon never touches a socket directly; `serve(transport)` drives one connected client.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hexharness.engine import Engine
from hexharness.providers.base import LLMProvider

from hexharness.protocol import EVENT_NOTIFICATION, Methods, Notification, Response
from hexharness.transport import Transport, TransportClosed


class _Session:
    def __init__(self, session_id: str, engine: Engine):
        self.id = session_id
        self.engine = engine


class EngineDaemon:
    def __init__(
        self,
        engagement_path: str | Path,
        *,
        provider: LLMProvider,
        model: str | None = None,
        db: str = ":memory:",
        **engine_kwargs: Any,
    ):
        self._engagement_path = engagement_path
        self._provider = provider
        self._model = model
        self._db = db
        self._engine_kwargs = engine_kwargs
        self._sessions: dict[str, _Session] = {}

    # --- lifecycle -----------------------------------------------------------------
    async def serve(self, transport: Transport) -> None:
        """Drive one connected client until its transport closes. Requests are handled
        one at a time — agent.run awaits the full loop, streaming events meanwhile, then
        replies. ponytail: sequential per-connection; add a task-per-request dispatcher
        if a client needs to run+kill concurrently over one link."""
        while True:
            try:
                msg = await transport.recv()
            except TransportClosed:
                return
            # A request carries both a method and an id; anything else (a stray
            # notification, a malformed frame) is ignored — we are a server.
            if "method" not in msg or msg.get("id") is None:
                continue
            await self._handle(transport, msg)

    # --- dispatch ------------------------------------------------------------------
    async def _handle(self, transport: Transport, msg: dict[str, Any]) -> None:
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        try:
            result = await self._dispatch(transport, method, params)
            await transport.send(Response.ok(req_id, result).model_dump())
        except Exception as exc:  # noqa: BLE001 — surface as a JSON-RPC error, never crash the serve loop
            await transport.send(Response.fail(req_id, str(exc)).model_dump())

    async def _dispatch(self, transport: Transport, method: str, params: dict[str, Any]) -> Any:
        if method == Methods.SESSION_CREATE:
            return self._create(transport)
        if method == Methods.SESSION_ATTACH:
            return self._attach(params["session_id"])
        if method == Methods.SESSION_RESUME:
            return await self._resume(transport, params["session_id"], int(params.get("from_seq", 0)))
        if method == Methods.AGENT_RUN:
            return await self._run(params["session_id"], params["prompt"])
        if method == Methods.KILL_TRIGGER:
            return await self._kill(params["session_id"], params.get("reason", "manual"))
        raise ValueError(f"unknown method: {method}")

    # --- handlers ------------------------------------------------------------------
    def _create(self, transport: Transport) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        engine = Engine.from_engagement(
            self._engagement_path, provider=self._provider, db=self._db, **self._engine_kwargs
        )
        self._sessions[session_id] = _Session(session_id, engine)
        self._stream_live(transport, session_id, engine)
        return {"session_id": session_id, "last_seq": _last_seq(engine)}

    def _attach(self, session_id: str) -> dict[str, Any]:
        sess = self._require(session_id)
        # Attach is just "I'm (re)connected"; the client follows with resume(from_seq)
        # to backfill. We report last_seq so it knows where the log currently ends.
        return {"session_id": session_id, "last_seq": _last_seq(sess.engine)}

    async def _resume(self, transport: Transport, session_id: str, from_seq: int) -> dict[str, Any]:
        sess = self._require(session_id)
        replayed = 0
        for ev in sess.engine.events.all():
            if ev.seq > from_seq:
                await self._push(transport, session_id, ev)
                replayed += 1
        return {"session_id": session_id, "replayed": replayed, "last_seq": _last_seq(sess.engine)}

    async def _run(self, session_id: str, prompt: str) -> dict[str, Any]:
        sess = self._require(session_id)
        loop = sess.engine.loop(provider=self._provider, model=self._model)
        text = await loop.run(prompt)  # events stream live via the bus subscription
        return {"session_id": session_id, "result": text, "last_seq": _last_seq(sess.engine)}

    async def _kill(self, session_id: str, reason: str) -> dict[str, Any]:
        sess = self._require(session_id)
        await sess.engine.kill_switch.trigger(reason)
        return {"session_id": session_id, "killed": True, "reason": reason}

    # --- event streaming -----------------------------------------------------------
    def _stream_live(self, transport: Transport, session_id: str, engine: Engine) -> None:
        """Subscribe to this engine's EventBus so every appended event is pushed to the
        client as a notification. ponytail: reaches engine.events._bus — the Engine wires
        the bus internally and doesn't re-expose it; this is the only hook, and it's
        guaranteed non-None by Engine.from_engagement."""
        bus = engine.events._bus
        if bus is None:  # pragma: no cover - from_engagement always wires one
            return

        async def _on_event(ev) -> None:
            await self._push(transport, session_id, ev)

        bus.subscribe(_on_event)

    async def _push(self, transport: Transport, session_id: str, ev) -> None:
        note = Notification(
            method=EVENT_NOTIFICATION,
            params={"session_id": session_id, "event": ev.model_dump(mode="json")},
        )
        await transport.send(note.model_dump())

    def _require(self, session_id: str) -> _Session:
        sess = self._sessions.get(session_id)
        if sess is None:
            raise KeyError(f"no such session: {session_id}")
        return sess


def _last_seq(engine: Engine) -> int:
    events = engine.events.all()
    return events[-1].seq if events else 0
