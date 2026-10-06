"""Context-window tracking, persistent conversation, and compaction (auto + manual)."""
from __future__ import annotations

from hexharness.agent.loop import AgentLoop
from hexharness.control.policy import Mode
from hexharness.providers.context_window import should_compact, usage_ratio, window_for
from hexharness.providers.fake import FakeProvider
from hexharness.providers.types import ModelResponse, StopReason, TextBlock, Usage
from hexharness.tools.registry import ToolRegistry

from tests.conftest import ctx, make_control


def _final(text="ok", inp=10, out=2):
    return ModelResponse(content=[TextBlock(text=text)], stop_reason=StopReason.END_TURN,
                         usage=Usage(input_tokens=inp, output_tokens=out))


def test_window_table_and_threshold():
    assert window_for("claude-sonnet-4-5") == 200_000
    assert window_for("gpt-4o") == 128_000
    assert window_for("totally-unknown") == 128_000  # conservative default
    assert should_compact("gpt-4o", 110_000) is True
    assert should_compact("gpt-4o", 50_000) is False
    assert 0.0 < usage_ratio("gpt-4o", 64_000) <= 0.5 + 1e-9


def _loop(provider):
    cp, events = make_control()
    return AgentLoop(provider=provider, control=cp, registry=ToolRegistry(), events=events, ctx=ctx(Mode()))


async def test_conversation_persists_across_runs():
    prov = FakeProvider([_final("first"), _final("second")])
    loop = _loop(prov)
    await loop.run("hello")
    n1 = len(loop.conversation)
    await loop.run("again")
    assert len(loop.conversation) > n1          # prior turns remembered, not reset
    # the second provider call saw the accumulated history
    assert len(prov.calls[1]) > len(prov.calls[0])


async def test_manual_compact_collapses_history():
    prov = FakeProvider([_final("a"), _final("b"), _final("SUMMARY")])
    loop = _loop(prov)
    await loop.run("one")
    await loop.run("two")
    assert len(loop.conversation) >= 4
    collapsed = await loop.compact(reason="manual")
    assert collapsed > 0
    assert len(loop.conversation) == 1
    assert "SUMMARY" in loop.conversation[0].content[0].text


async def test_auto_compact_when_near_limit():
    # summary call, then the actual turn call
    from hexharness.providers.types import Message

    prov = FakeProvider([_final("SUMMARY"), _final("answer")])
    loop = _loop(prov)
    loop.conversation = [Message.user_text("old q"), Message.user_text("old a")]
    loop.last_input_tokens = 200_000          # over 80% of the 128k default window
    await loop.run("new question")
    types = [e.type.value for e in loop.events.all()]
    assert "agent.context_compacted" in types
