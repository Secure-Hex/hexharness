"""OpenAI adapter: normalized types <-> Chat Completions / Responses APIs.

OpenAIProvider uses the Responses API; the Chat Completions helpers below are shared
by the OpenAI-compatible and Ollama providers.

API key from env OPENAI_API_KEY. default_model from HEXHARNESS_OPENAI_MODEL or "gpt-4o".
Streams when an on_text sink is given (see stream_openai); otherwise one blocking call.

The mapping helpers (to_openai_messages / tools_to_openai / from_openai_response) are
pure and SDK-free so they can be unit-tested without the `openai` package installed.
"""
from __future__ import annotations

import json
import os
from typing import Any

from hexharness.providers.types import (
    Message,
    ModelResponse,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
    Usage,
)

_STOP_MAP = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
    "content_filter": StopReason.REFUSAL,
}


def to_openai_messages(messages: list[Message], system: str | None = None) -> list[dict[str, Any]]:
    """Flatten normalized messages to the OpenAI Chat Completions message list.

    One normalized Message can fan out to several OpenAI messages: tool results each
    become their own `role: "tool"` message (OpenAI has no multi-result message).
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
        tool_uses = [b for b in m.content if isinstance(b, ToolUseBlock)]
        tool_results = [b for b in m.content if isinstance(b, ToolResultBlock)]

        if m.role is Role.ASSISTANT:
            msg: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_uses:
                msg["tool_calls"] = [
                    {
                        "id": b.id,
                        "type": "function",
                        "function": {"name": b.name, "arguments": json.dumps(b.input)},
                    }
                    for b in tool_uses
                ]
            out.append(msg)
        else:  # USER: plain text and/or tool results
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})
            for b in tool_results:
                out.append({"role": "tool", "tool_call_id": b.tool_use_id, "content": b.content})
    return out


def tools_to_openai(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
        }
        for t in tools
    ]


def from_openai_response(resp) -> ModelResponse:
    choice = resp.choices[0]
    msg = choice.message
    content: list = []
    if getattr(msg, "content", None):
        content.append(TextBlock(text=msg.content))
    for call in getattr(msg, "tool_calls", None) or []:
        args = call.function.arguments
        content.append(
            ToolUseBlock(
                id=call.id,
                name=call.function.name,
                input=json.loads(args) if isinstance(args, str) else dict(args or {}),
            )
        )
    usage = getattr(resp, "usage", None)
    return ModelResponse(
        content=content,
        stop_reason=_STOP_MAP.get(choice.finish_reason, StopReason.OTHER),
        usage=Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        ),
        model=getattr(resp, "model", ""),
    )


async def stream_openai(client, kwargs: dict[str, Any], on_text, on_thinking=None) -> ModelResponse:
    """Stream a Chat Completions call, pushing text deltas to on_text (and reasoning
    deltas to on_thinking) as they arrive, and accumulate the full response into a
    ModelResponse. Shared by every OpenAI-compatible provider.

    Robust to flaky gateways: if streaming fails partway (e.g. a gateway that doesn't
    support stream/stream_options and ends the stream early), fall back to one blocking
    completion so the turn still succeeds."""
    stream_kwargs = {**kwargs, "stream": True, "stream_options": {"include_usage": True}}
    text_parts: list[str] = []
    tool_slots: dict[int, dict[str, str]] = {}  # index -> {id, name, args}
    finish_reason: str | None = None
    usage = None
    model = ""

    try:
        stream = await client.chat.completions.create(**stream_kwargs)
        async for chunk in stream:
            if getattr(chunk, "model", ""):
                model = chunk.model
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for choice in chunk.choices or []:
                delta = choice.delta
                reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if reasoning and on_thinking is not None:
                    on_thinking(reasoning)
                if getattr(delta, "content", None):
                    text_parts.append(delta.content)
                    on_text(delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn and getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if fn and getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
    except Exception:  # noqa: BLE001 — gateway ended the stream early: fall back to blocking
        # ponytail: partial text may already be on screen; the blocking result is canonical.
        resp = await client.chat.completions.create(**kwargs)
        return from_openai_response(resp)

    content: list = []
    if "".join(text_parts):
        content.append(TextBlock(text="".join(text_parts)))
    for slot in tool_slots.values():
        try:
            args = json.loads(slot["args"] or "{}")
        except json.JSONDecodeError:
            args = {}
        content.append(ToolUseBlock(id=slot["id"], name=slot["name"], input=args))
    return ModelResponse(
        content=content,
        stop_reason=_STOP_MAP.get(finish_reason, StopReason.OTHER),
        usage=Usage(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        ),
        model=model,
    )


def to_responses_input(messages: list[Message]) -> list[dict[str, Any]]:
    """Flatten normalized messages to Responses API input items (system goes in
    `instructions`). Tool calls/results are top-level items, not message parts."""
    out: list[dict[str, Any]] = []
    for m in messages:
        text = "".join(b.text for b in m.content if isinstance(b, TextBlock))
        if text:
            out.append({"role": m.role.value, "content": text})
        for b in m.content:
            if isinstance(b, ToolUseBlock):
                out.append({"type": "function_call", "call_id": b.id, "name": b.name,
                            "arguments": json.dumps(b.input)})
            elif isinstance(b, ToolResultBlock):
                out.append({"type": "function_call_output", "call_id": b.tool_use_id,
                            "output": f"ERROR: {b.content}" if b.is_error else b.content})
    return out


def tools_to_responses(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "name": t.name, "description": t.description, "parameters": t.input_schema}
        for t in tools
    ]


def from_responses_response(resp, on_thinking=None) -> ModelResponse:
    """Map a Responses API `Response`. Reasoning summaries go to on_thinking (blocking
    path only; the streaming path pushes them live) and are not kept in history."""
    content: list = []
    for item in resp.output or []:
        if item.type == "message":
            text = "".join(p.text for p in item.content if getattr(p, "type", "") == "output_text")
            if text:
                content.append(TextBlock(text=text))
        elif item.type == "function_call":
            try:
                args = json.loads(item.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append(ToolUseBlock(id=item.call_id, name=item.name, input=args))
        elif item.type == "reasoning" and on_thinking is not None:
            for s in getattr(item, "summary", None) or []:
                on_thinking(s.text)
    if any(isinstance(b, ToolUseBlock) for b in content):
        stop = StopReason.TOOL_USE
    elif resp.status == "incomplete" and getattr(resp.incomplete_details, "reason", None) == "max_output_tokens":
        stop = StopReason.MAX_TOKENS
    else:
        stop = StopReason.END_TURN
    usage = getattr(resp, "usage", None)
    return ModelResponse(
        content=content,
        stop_reason=stop,
        usage=Usage(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        ),
        model=getattr(resp, "model", ""),
    )


async def stream_responses(client, kwargs: dict[str, Any], on_text, on_thinking=None) -> ModelResponse:
    """Stream a Responses API call: text deltas -> on_text, reasoning summary deltas ->
    on_thinking; the terminal event carries the full Response we map at the end."""
    final = None
    stream = await client.responses.create(**kwargs, stream=True)
    async for event in stream:
        if event.type == "response.output_text.delta":
            on_text(event.delta)
        elif event.type == "response.reasoning_summary_text.delta" and on_thinking is not None:
            on_thinking(event.delta)
        elif event.type in ("response.completed", "response.incomplete", "response.failed"):
            final = event.response
    if final is None:
        raise RuntimeError("OpenAI stream ended without a final response")
    return from_responses_response(final)


class OpenAIProvider:
    """Native OpenAI uses the Responses API: reasoning models reject function tools
    on /v1/chat/completions. OpenAI-compatible gateways stay on Chat Completions."""

    name = "openai"

    def __init__(self, *, api_key: str | None = None, default_model: str | None = None):
        # Imported lazily so the package imports without the SDK installed.
        from openai import AsyncOpenAI

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self._client = AsyncOpenAI(api_key=key, max_retries=1, timeout=60.0)
        self.default_model = default_model or os.environ.get("HEXHARNESS_OPENAI_MODEL", "gpt-4o")
        self._no_reasoning: set[str] = set()  # models that rejected the `reasoning` param

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        on_text=None,
        on_thinking=None,
    ) -> ModelResponse:
        from openai import BadRequestError

        model = model or self.default_model
        # ponytail: store=False and no reasoning block type in providers/types.py, so
        # reasoning items are not round-tripped (no include=["reasoning.encrypted_content"]);
        # the model re-reasons each turn. Add a ReasoningBlock carrying encrypted_content
        # if cross-turn reasoning quality/cost matters.
        kwargs: dict[str, Any] = {
            "model": model,
            "input": to_responses_input(messages),
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if system:
            kwargs["instructions"] = system
        if tools:
            kwargs["tools"] = tools_to_responses(tools)
        if model not in self._no_reasoning:
            kwargs["reasoning"] = {"summary": "auto"}

        async def call(kw):
            if on_text is not None or on_thinking is not None:
                return await stream_responses(self._client, kw, on_text or (lambda s: None), on_thinking)
            return from_responses_response(await self._client.responses.create(**kw), on_thinking)

        try:
            return await call(kwargs)
        except BadRequestError as e:
            # Non-reasoning models (gpt-4o class) reject `reasoning`: remember and retry once.
            if "reasoning" not in kwargs or "reasoning" not in str(e).lower():
                raise
            self._no_reasoning.add(model)
            kwargs.pop("reasoning")
            return await call(kwargs)
