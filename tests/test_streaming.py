"""Model text streams through the on_text sink end-to-end in the agent loop."""
from __future__ import annotations

from hexharness.agent.loop import AgentLoop
from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, Usage
from hexharness.tools.registry import ToolRegistry

from tests.conftest import ctx, make_control
from hexharness.control.policy import Mode


async def test_on_text_receives_streamed_text():
    cp, events = make_control()
    provider = FakeProvider([
        ModelResponse(content=[TextBlock(text="hello world")], stop_reason=StopReason.END_TURN,
                      usage=Usage(input_tokens=1, output_tokens=2)),
    ])
    chunks: list[str] = []
    loop = AgentLoop(provider=provider, control=cp, registry=ToolRegistry(), events=events,
                     ctx=ctx(Mode()), on_text=chunks.append)
    out = await loop.run("hi")
    assert out == "hello world"
    assert "".join(chunks) == "hello world"  # the sink saw the text


async def test_no_sink_still_works():
    cp, events = make_control()
    provider = FakeProvider([
        ModelResponse(content=[TextBlock(text="quiet")], stop_reason=StopReason.END_TURN),
    ])
    loop = AgentLoop(provider=provider, control=cp, registry=ToolRegistry(), events=events, ctx=ctx(Mode()))
    assert await loop.run("hi") == "quiet"  # on_text=None path unaffected
