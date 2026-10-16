"""OpenAIProvider on the Responses API: input mapping, output mapping, streaming, and the
`reasoning` fallback for non-reasoning models. Fake client, no network."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

openai = pytest.importorskip("openai")

from hexharness.providers.openai import OpenAIProvider, to_responses_input  # noqa: E402
from hexharness.providers.types import (  # noqa: E402
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)

_TOOL = ToolSpec(name="get_time", description="time", input_schema={"type": "object", "properties": {}})


def _resp(output, status="completed", reason=None):
    return SimpleNamespace(
        output=output, status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        usage=SimpleNamespace(input_tokens=7, output_tokens=3), model="m",
    )


def _call(id="call_1", name="get_time", args="{}"):
    return SimpleNamespace(type="function_call", call_id=id, name=name, arguments=args)


def _msg(text):
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])


def _reasoning(text):
    return SimpleNamespace(type="reasoning", summary=[SimpleNamespace(text=text)])


class _FakeResponses:
    def __init__(self, result, reject_reasoning=False):
        self.result, self.reject_reasoning, self.calls = result, reject_reasoning, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.reject_reasoning and "reasoning" in kw:
            raise openai.BadRequestError(
                "Unsupported parameter: 'reasoning.summary'",
                response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
        if kw.get("stream"):
            events = self.result

            async def gen():
                for e in events:
                    yield e
            return gen()
        return self.result


def _provider(fake):
    p = OpenAIProvider(api_key="sk-test")
    p._client = SimpleNamespace(responses=fake)
    return p


def test_history_maps_to_input_items():
    items = to_responses_input([
        Message.user_text("hi"),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="checking"),
                                              ToolUseBlock(id="c1", name="get_time", input={"tz": "UTC"})]),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c1", content="boom", is_error=True)]),
    ])
    assert items == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "checking"},
        {"type": "function_call", "call_id": "c1", "name": "get_time", "arguments": '{"tz": "UTC"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "ERROR: boom"},
    ]


async def test_blocking_tool_call_and_request_shape():
    fake = _FakeResponses(_resp([_reasoning("thinking"), _call(args='{"tz":"UTC"}')]))
    r = await _provider(fake).complete([Message.user_text("time?")], tools=[_TOOL], system="sys",
                                       model="gpt-6-luna", max_tokens=99)
    assert r.stop_reason is StopReason.TOOL_USE
    assert r.tool_uses()[0].id == "call_1" and r.tool_uses()[0].input == {"tz": "UTC"}
    assert r.usage.input_tokens == 7 and r.usage.output_tokens == 3
    kw = fake.calls[0]
    assert kw["instructions"] == "sys" and kw["max_output_tokens"] == 99 and kw["store"] is False
    assert kw["tools"][0]["name"] == "get_time" and kw["reasoning"] == {"summary": "auto"}


async def test_max_tokens_stop_reason():
    fake = _FakeResponses(_resp([_msg("partial")], status="incomplete", reason="max_output_tokens"))
    r = await _provider(fake).complete([Message.user_text("x")])
    assert r.stop_reason is StopReason.MAX_TOKENS and r.text() == "partial"


async def test_streaming_pushes_deltas_and_uses_final_response():
    events = [
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="hmm"),
        SimpleNamespace(type="response.output_text.delta", delta="It is "),
        SimpleNamespace(type="response.output_text.delta", delta="noon"),
        SimpleNamespace(type="response.completed", response=_resp([_msg("It is noon")])),
    ]
    text, thoughts = [], []
    r = await _provider(_FakeResponses(events)).complete(
        [Message.user_text("x")], on_text=text.append, on_thinking=thoughts.append)
    assert text == ["It is ", "noon"] and thoughts == ["hmm"]
    assert r.text() == "It is noon" and r.stop_reason is StopReason.END_TURN


async def test_retries_without_reasoning_for_non_reasoning_models():
    fake = _FakeResponses(_resp([_msg("ok")]), reject_reasoning=True)
    p = _provider(fake)
    assert (await p.complete([Message.user_text("x")], model="gpt-4o-mini")).text() == "ok"
    assert len(fake.calls) == 2 and "reasoning" not in fake.calls[1]
    await p.complete([Message.user_text("x")], model="gpt-4o-mini")
    assert len(fake.calls) == 3  # remembered: no second rejected attempt
