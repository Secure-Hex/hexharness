"""Anthropic adapter: normalized types <-> Messages API.

API key from env ANTHROPIC_API_KEY (Varlock-managed vault lands in a later phase).
Streaming is deferred; a single blocking completion is enough for the loop today.
"""
from __future__ import annotations

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
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.REFUSAL,
}


def _block_to_api(block) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    raise TypeError(f"unknown block: {block!r}")


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    return [
        {"role": m.role.value, "content": [_block_to_api(b) for b in m.content]}
        for m in messages
    ]


def from_api_response(resp) -> ModelResponse:
    content: list = []
    for block in resp.content:
        if block.type == "text":
            content.append(TextBlock(text=block.text))
        elif block.type == "tool_use":
            content.append(ToolUseBlock(id=block.id, name=block.name, input=dict(block.input)))
        # other block types (thinking, etc.) are ignored for now
    return ModelResponse(
        content=content,
        stop_reason=_STOP_MAP.get(resp.stop_reason, StopReason.OTHER),
        usage=Usage(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens),
        model=resp.model,
    )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, default_model: str | None = None):
        # Imported lazily so the package imports without the SDK installed.
        from anthropic import AsyncAnthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=key, max_retries=1, timeout=60.0)
        self.default_model = default_model or os.environ.get(
            "HEXHARNESS_MODEL", "claude-sonnet-4-5"
        )

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
            "messages": to_api_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        if on_text is not None:
            # Stream text deltas to the sink; still return the full mapped response.
            async with self._client.messages.stream(**kwargs) as stream:
                async for delta in stream.text_stream:
                    on_text(delta)
                final = await stream.get_final_message()
            return from_api_response(final)
        resp = await self._client.messages.create(**kwargs)
        return from_api_response(resp)
