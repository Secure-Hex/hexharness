"""Phase 6: thin client <-> long-lived engine daemon, end to end over InMemoryTransport.

No network, no real websockets. A scripted FakeProvider drives the agent loop so the
whole path — create, run, live event streaming, and resume replay — is deterministic.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, Usage

from hexharness.client import EngineClient
from hexharness.daemon import EngineDaemon
from hexharness.transport import InMemoryTransport

ENG = Path(__file__).resolve().parent.parent / "engagements" / "example.engagement.yaml"


def _script(n: int) -> list[ModelResponse]:
    # One plain end-of-turn answer per run: no tool use, so the loop appends exactly
    # USER_PROMPT + MODEL_RESPONSE and returns the text.
    return [
        ModelResponse(
            content=[TextBlock(text=f"answer-{i}")],
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=5, output_tokens=3),
        )
        for i in range(n)
    ]


async def _drain(collected: list, *, at_least: int, timeout: float = 1.0) -> None:
    # Spin the loop until the collector has seen `at_least` events (or we give up).
    deadline = asyncio.get_running_loop().time() + timeout
    while len(collected) < at_least and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)


@pytest.fixture
async def wired():
    provider = FakeProvider(_script(1))
    daemon = EngineDaemon(ENG, provider=provider)
    client_t, daemon_t = InMemoryTransport.connected_pair()
    serve_task = asyncio.ensure_future(daemon.serve(daemon_t))

    client = EngineClient(client_t)
    collected: list = []

    async def _collect() -> None:
        async for ev in client.events():
            collected.append(ev)

    collector = asyncio.ensure_future(_collect())

    yield client, daemon, provider, collected

    await client.close()
    await daemon_t.close()
    for task in (serve_task, collector):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def test_create_run_stream_and_resume(wired):
    client, daemon, provider, collected = wired

    # 1. create a session
    session_id = await client.create_session()
    assert isinstance(session_id, str) and session_id

    # 2. run a prompt end to end — the FakeProvider's scripted answer comes back
    result = await client.run(session_id, "scan the box")
    assert result == "answer-0"

    # 3. the run streamed engine events to us as notifications (USER_PROMPT + MODEL_RESPONSE)
    await _drain(collected, at_least=2)
    types = [ev["event"]["type"] for ev in collected]
    assert "agent.user_prompt" in types
    assert "agent.model_response" in types
    assert all(ev["session_id"] == session_id for ev in collected)

    seqs = [ev["event"]["seq"] for ev in collected]
    assert seqs == sorted(seqs)
    last_live = max(seqs)

    # 4. resume from seq 1 replays only the events after it (not the whole log)
    before = len(collected)
    info = await client.resume(session_id, from_seq=1)
    assert info["replayed"] == last_live - 1  # everything with seq > 1
    await _drain(collected, at_least=before + info["replayed"])

    replayed = collected[before:]
    assert replayed, "resume should have pushed the missed events"
    assert all(ev["event"]["seq"] > 1 for ev in replayed)


async def test_attach_reports_last_seq(wired):
    client, daemon, provider, collected = wired

    session_id = await client.create_session()
    await client.run(session_id, "enumerate")

    info = await client.attach(session_id)
    assert info["session_id"] == session_id
    assert info["last_seq"] >= 2  # at least USER_PROMPT + MODEL_RESPONSE are logged
