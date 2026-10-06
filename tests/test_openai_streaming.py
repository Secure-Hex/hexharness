"""stream_openai accumulates text deltas (pushed live to on_text) + tool calls + usage
into a ModelResponse. Pure: no network, no openai SDK needed."""
from __future__ import annotations

from types import SimpleNamespace

from hexharness.providers.openai import stream_openai
from hexharness.providers.types import StopReason, TextBlock, ToolUseBlock


def _delta(content=None, tool_calls=None, finish=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls),
                                 finish_reason=finish)],
        model="test-model", usage=None,
    )


def _tc(index, id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=id,
                           function=SimpleNamespace(name=name, arguments=args))


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        assert kwargs.get("stream") is True
        chunks = self._chunks

        async def gen():
            for c in chunks:
                yield c
        return gen()


async def test_streams_text_and_builds_response():
    chunks = [
        _delta(content="Hola "),
        _delta(content="mundo"),
        _delta(finish="stop"),
        SimpleNamespace(choices=[], model="test-model",
                        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=3)),
    ]
    seen: list[str] = []
    resp = await stream_openai(_FakeClient(chunks), {"model": "x"}, seen.append)

    assert seen == ["Hola ", "mundo"]              # pushed live
    assert resp.text() == "Hola mundo"             # accumulated
    assert resp.stop_reason is StopReason.END_TURN
    assert resp.usage.input_tokens == 11 and resp.usage.output_tokens == 3


async def test_accumulates_streamed_tool_call():
    chunks = [
        _delta(tool_calls=[_tc(0, id="call_1", name="dns_lookup", args='{"host":')]),
        _delta(tool_calls=[_tc(0, args='"acme.example"}')]),
        _delta(finish="tool_calls"),
    ]
    resp = await stream_openai(_FakeClient(chunks), {"model": "x"}, lambda s: None)
    assert resp.stop_reason is StopReason.TOOL_USE
    tus = resp.tool_uses()
    assert len(tus) == 1
    assert tus[0].name == "dns_lookup" and tus[0].input == {"host": "acme.example"}
