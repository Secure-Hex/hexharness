"""OpenAI adapter: normalized types <-> Chat Completions API.

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


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str | None = None, default_model: str | None = None):
        # Imported lazily so the package imports without the SDK installed.
        from openai import AsyncOpenAI

        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self._client = AsyncOpenAI(api_key=key, max_retries=1, timeout=60.0)
        self.default_model = default_model or os.environ.get("HEXHARNESS_OPENAI_MODEL", "gpt-4o")

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
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": to_openai_messages(messages, system),
        }
        if tools:
            kwargs["tools"] = tools_to_openai(tools)
        if on_text is not None or on_thinking is not None:
            return await stream_openai(self._client, kwargs, on_text or (lambda s: None), on_thinking)
        resp = await self._client.chat.completions.create(**kwargs)
        return from_openai_response(resp)
