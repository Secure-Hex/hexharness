"""Reverse-shell handler: catch a connection, run a command, and drop out-of-scope peers.
Uses a loopback 'fake shell' that echoes a canned response — no real target."""
from __future__ import annotations

import asyncio
import socket

from hexharness.tools.native.revshell import ReverseShellManager


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _wait_sessions(mgr, n, timeout=2.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if len(mgr.sessions()) >= n:
            return
        await asyncio.sleep(0.02)


async def test_catches_in_scope_shell_and_runs_command() -> None:
    mgr = ReverseShellManager(scope_check=lambda ip: ip == "127.0.0.1")
    port = _free_port()
    assert "listening" in await mgr.start_listener(port)

    # Fake shell: connect back, read one command, reply with canned output.
    reader, writer = await asyncio.open_connection("127.0.0.1", port)

    async def fake_shell():
        cmd = await reader.readline()
        writer.write(f"ran: {cmd.decode().strip()}\n".encode())
        await writer.drain()

    shell_task = asyncio.create_task(fake_shell())
    await _wait_sessions(mgr, 1)
    sid = mgr.sessions()[0].id
    assert mgr.sessions()[0].peer == "127.0.0.1"

    out = await mgr.exec(sid, "id", idle=0.5, overall=2.0)
    assert "ran: id" in out
    await shell_task
    mgr.close()


async def test_drops_out_of_scope_peer() -> None:
    # Only 10.0.0.1 is in scope; a loopback (127.0.0.1) connection must be dropped.
    mgr = ReverseShellManager(scope_check=lambda ip: ip == "10.0.0.1")
    port = _free_port()
    await mgr.start_listener(port)
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.2)
    assert mgr.sessions() == []            # not caught
    assert "127.0.0.1" in mgr.dropped      # recorded for audit
    writer.close()
    mgr.close()


async def test_exec_unknown_session() -> None:
    mgr = ReverseShellManager()
    assert "no such shell session" in await mgr.exec("deadbeef", "id")
