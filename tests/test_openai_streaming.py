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


class _FakeRespChoice:
    def __init__(self):
        self.message = SimpleNamespace(content="blocking result", tool_calls=None)
        self.finish_reason = "stop"


class _FallbackClient:
    """Stream raises mid-iteration; a plain create() then succeeds (the fallback)."""
    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.calls = 0

    async def _create(self, **kwargs):
        self.calls += 1
        if kwargs.get("stream"):
            async def gen():
                raise RuntimeError("The stream ended before completion")
                yield  # pragma: no cover
            return gen()
        return SimpleNamespace(choices=[_FallbackChoice()], model="m",
                               usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2))


class _FallbackChoice:
    def __init__(self):
        self.message = SimpleNamespace(content="blocking result", tool_calls=None)
        self.finish_reason = "stop"


async def test_falls_back_to_blocking_when_stream_breaks():
    client = _FallbackClient()
    resp = await stream_openai(client, {"model": "m"}, lambda s: None)
    assert resp.text() == "blocking result"
    assert client.calls == 2  # stream attempt + blocking fallback


async def test_reasoning_deltas_go_to_on_thinking():
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, tool_calls=None, reasoning_content="let me think"),
            finish_reason=None)], model="m", usage=None),
        _delta(content="answer"),
        _delta(finish="stop"),
    ]
    thoughts, text = [], []
    resp = await stream_openai(_FakeClient(chunks), {"model": "m"}, text.append, thoughts.append)
    assert thoughts == ["let me think"] and resp.text() == "answer"
