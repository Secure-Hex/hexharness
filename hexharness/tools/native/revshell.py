"""Reverse-shell handler: a long-lived TCP listener that catches shells calling back
and lets the operator/agent interact with them. For AUTHORIZED pentesting — every
interactive tool is DESTRUCTIVE + requires_approval, and a caught connection whose peer
IP is out of engagement scope is dropped on connect (fail-closed).

The listener and caught sessions live in a ReverseShellManager that persists across tool
calls (one per engine, like the sandbox executor). Engine tears it down on exit.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class _Session:
    def __init__(self, sid: str, peer: str, port: int,
                 reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.id = sid
        self.peer = peer
        self.port = port
        self.reader = reader
        self.writer = writer
        self.opened = time.time()


class ReverseShellManager:
    """Owns listeners (asyncio servers) and caught shell sessions. Sync close() for exit."""

    def __init__(self, *, scope_check: Callable[[str], bool] | None = None):
        self._scope_check = scope_check
        self._servers: dict[int, asyncio.base_events.Server] = {}
        self._sessions: dict[str, _Session] = {}
        self.dropped: list[str] = []  # peers refused as out-of-scope (for audit/reporting)

    async def start_listener(self, port: int) -> str:
        if port in self._servers:
            return f"already listening on :{port}"
        try:
            server = await asyncio.start_server(self._on_connect, "0.0.0.0", port)
        except OSError as exc:
            return f"could not bind :{port} — {exc}"
        self._servers[port] = server
        return f"listening on 0.0.0.0:{port} — waiting for a shell to call back"

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_info = writer.get_extra_info("peername")
        peer = peer_info[0] if peer_info else "?"
        port = writer.get_extra_info("sockname", (None, 0))[1]
        # Fail-closed: only catch shells from in-scope hosts.
        if self._scope_check is not None and not self._scope_check(peer):
            self.dropped.append(peer)
            writer.close()
            return
        sid = uuid.uuid4().hex[:8]
        self._sessions[sid] = _Session(sid, peer, port, reader, writer)

    def sessions(self) -> list[_Session]:
        return list(self._sessions.values())

    async def exec(self, sid: str, command: str, *, idle: float = 1.5, overall: float = 10.0) -> str:
        s = self._sessions.get(sid)
        if s is None:
            return f"no such shell session: {sid}"
        try:
            s.writer.write((command + "\n").encode())
            await s.writer.drain()
        except Exception as exc:  # noqa: BLE001 — broken pipe => shell died
            self._sessions.pop(sid, None)
            return f"shell {sid} is gone: {exc}"
        return (await self._read_available(s.reader, idle, overall)).decode(errors="replace").strip()

    @staticmethod
    async def _read_available(reader: asyncio.StreamReader, idle: float, overall: float) -> bytes:
        # Shells don't frame output; read chunks until the shell goes quiet (idle gap) or
        # the overall cap is hit. ponytail: time-based, no prompt detection — good enough
        # for an interactive handler; wire a PTY/marker if precise framing is needed.
        buf = b""
        deadline = time.time() + overall
        while time.time() < deadline:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), idle)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
        return buf

    def close_session(self, sid: str) -> bool:
        s = self._sessions.pop(sid, None)
        if s is None:
            return False
        try:
            s.writer.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    def close(self) -> None:
        """Stop all listeners and drop all sessions (sync — safe from exit handlers)."""
        for server in self._servers.values():
            server.close()
        self._servers.clear()
        for s in self._sessions.values():
            try:
                s.writer.close()
            except Exception:  # noqa: BLE001
                pass
        self._sessions.clear()


# ------------------------------------------------------------------------------- tools

class ListenerStartInput(BaseModel):
    port: int = Field(ge=1, le=65535, description="TCP port to listen on for a reverse shell (LPORT).")


class ListenerStartTool(Tool):
    name = "listener_start"
    description = ("Start a TCP listener for a reverse shell to call back (set this port as "
                   "LPORT in your payload). Shells from out-of-scope hosts are dropped.")
    input_model = ListenerStartInput
    risk_level = RiskLevel.DESTRUCTIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, manager: ReverseShellManager):
        self.manager = manager

    async def run(self, tool_input: dict) -> str:
        data = ListenerStartInput.model_validate(tool_input)
        return await self.manager.start_listener(data.port)


class _NoInput(BaseModel):
    pass


class ShellSessionsTool(Tool):
    name = "shell_sessions"
    description = "List caught reverse-shell sessions (id, peer, port, age). Read-only."
    input_model = _NoInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, manager: ReverseShellManager):
        self.manager = manager

    async def run(self, tool_input: dict) -> str:
        sessions = self.manager.sessions()
        lines = []
        if self.manager.dropped:
            lines.append(f"dropped out-of-scope peers: {', '.join(self.manager.dropped)}")
        if not sessions:
            lines.append("no active shell sessions.")
            return "\n".join(lines)
        now = time.time()
        lines.append(f"{len(sessions)} shell session(s):")
        for s in sessions:
            lines.append(f"  {s.id} — {s.peer} (caught on :{s.port}, {int(now - s.opened)}s ago)")
        return "\n".join(lines)


class ShellExecInput(BaseModel):
    session_id: str = Field(description="Shell session id (from shell_sessions).")
    command: str = Field(description="Command to run in the caught shell.")


class ShellExecTool(Tool):
    name = "shell_exec"
    description = ("Run a command in a caught reverse shell and return its output. The shell "
                   "was already scope-checked when it connected. Requires approval.")
    input_model = ShellExecInput
    risk_level = RiskLevel.DESTRUCTIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, manager: ReverseShellManager):
        self.manager = manager

    async def run(self, tool_input: dict) -> str:
        data = ShellExecInput.model_validate(tool_input)
        out = await self.manager.exec(data.session_id, data.command)
        return out or "(no output)"


class ListenerStopInput(BaseModel):
    session_id: str | None = Field(default=None, description="Close just this session; omit to stop ALL listeners + sessions.")


class ListenerStopTool(Tool):
    name = "listener_stop"
    description = "Close one shell session (session_id) or stop all listeners and sessions (no arg)."
    input_model = ListenerStopInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, manager: ReverseShellManager):
        self.manager = manager

    async def run(self, tool_input: dict) -> str:
        data = ListenerStopInput.model_validate(tool_input)
        if data.session_id:
            return f"closed {data.session_id}" if self.manager.close_session(data.session_id) \
                else f"no such session: {data.session_id}"
        self.manager.close()
        return "all listeners and sessions closed."
