"""JSON-RPC 2.0 wire models for the HexHarness thin-client / engine split.

The client and daemon speak these over any `Transport`. Nothing here knows whether
the bytes travel over a unix socket, a WebSocket, or an in-memory queue — that is the
transport's job. Params stay as plain dicts: the method set is small and the daemon
validates what it needs, so per-method param models would be boilerplate (YAGNI).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

JSONRPC = "2.0"


class Methods:
    # Request methods the daemon answers.
    SESSION_CREATE = "session.create"
    SESSION_ATTACH = "session.attach"
    SESSION_RESUME = "session.resume"  # params: {session_id, from_seq}
    AGENT_RUN = "agent.run"            # params: {session_id, prompt}
    KILL_TRIGGER = "kill.trigger"      # params: {session_id, reason?}


# Server -> client push: one engine Event, as it is appended (and on resume replay).
EVENT_NOTIFICATION = "session.event"  # params: {session_id, event: <Event.model_dump>}


class Error(BaseModel):
    code: int = -32000
    message: str
    data: Any | None = None


class Request(BaseModel):
    jsonrpc: str = JSONRPC
    id: int | str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class Response(BaseModel):
    jsonrpc: str = JSONRPC
    id: int | str | None
    result: Any | None = None
    error: Error | None = None

    @classmethod
    def ok(cls, id: int | str | None, result: Any) -> "Response":
        return cls(id=id, result=result)

    @classmethod
    def fail(cls, id: int | str | None, message: str, code: int = -32000) -> "Response":
        return cls(id=id, error=Error(code=code, message=message))


class Notification(BaseModel):
    jsonrpc: str = JSONRPC
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def is_notification(msg: dict[str, Any]) -> bool:
    # Responses carry result/error and no method; requests and notifications carry a
    # method. The client only ever receives responses or notifications, so "method"
    # present is enough to tell a push from a reply.
    return "method" in msg
