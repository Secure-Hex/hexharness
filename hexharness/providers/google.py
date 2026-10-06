"""Google adapter: normalized types <-> google-genai `contents`.

API key from env GOOGLE_API_KEY. default_model from HEXHARNESS_GOOGLE_MODEL or
"gemini-2.0-flash". Lazy SDK import so the package imports without google-genai.

Mapping helpers emit/consume plain dicts (the shape the SDK accepts and returns via
to_json_dict), so they are unit-testable without the SDK installed.
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
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.REFUSAL,
    "RECITATION": StopReason.REFUSAL,
}


def to_genai_contents(messages: list[Message]) -> list[dict[str, Any]]:
    """Map normalized messages to Gemini `contents`. ASSISTANT -> "model".

    Gemini function_response parts key on the tool *name*, not an id, so we resolve
    each tool_use_id back to the name declared by a prior assistant function_call.
    """
    id_to_name: dict[str, str] = {}
    contents: list[dict[str, Any]] = []
    for m in messages:
        parts: list[dict[str, Any]] = []
        for b in m.content:
            if isinstance(b, TextBlock):
                parts.append({"text": b.text})
            elif isinstance(b, ToolUseBlock):
                id_to_name[b.id] = b.name
                parts.append({"function_call": {"name": b.name, "args": b.input}})
            elif isinstance(b, ToolResultBlock):
                name = id_to_name.get(b.tool_use_id, b.tool_use_id)
                parts.append(
                    {"function_response": {"name": name, "response": {"output": b.content}}}
                )
        role = "model" if m.role is Role.ASSISTANT else "user"
        contents.append({"role": role, "parts": parts})
    return contents


def tools_to_genai(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "function_declarations": [
                {"name": t.name, "description": t.description, "parameters": t.input_schema}
                for t in tools
            ]
        }
    ]


def _part_attr(part, key):
    # SDK parts are objects; dict shape is handy for tests.
    return part.get(key) if isinstance(part, dict) else getattr(part, key, None)


def from_genai_response(resp) -> ModelResponse:
    cand = resp.candidates[0]
    parts = cand.content["parts"] if isinstance(cand.content, dict) else cand.content.parts
    content: list = []
    for part in parts or []:
        text = _part_attr(part, "text")
        fc = _part_attr(part, "function_call")
        if text:
            content.append(TextBlock(text=text))
        elif fc:
            name = fc.get("name") if isinstance(fc, dict) else fc.name
            args = fc.get("args") if isinstance(fc, dict) else fc.args
            # ponytail: synthetic id — Gemini has no tool_use id; name+index would collide
            # on parallel calls to the same tool, upgrade to an enumerated id if that lands.
            content.append(ToolUseBlock(id=name, name=name, input=dict(args or {})))
    finish = cand.get("finish_reason") if isinstance(cand, dict) else getattr(cand, "finish_reason", None)
    um = getattr(resp, "usage_metadata", None)
    return ModelResponse(
        content=content,
        stop_reason=_STOP_MAP.get(str(finish), StopReason.END_TURN if content else StopReason.OTHER),
        usage=Usage(
            input_tokens=getattr(um, "prompt_token_count", 0) if um else 0,
            output_tokens=getattr(um, "candidates_token_count", 0) if um else 0,
        ),
        model=getattr(resp, "model_version", ""),
    )


class GoogleProvider:
    name = "google"

    def __init__(self, *, api_key: str | None = None, default_model: str | None = None):
        # Imported lazily so the package imports without the SDK installed.
        from google import genai

        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GOOGLE_API_KEY not set")
        self._client = genai.Client(api_key=key)
        self.default_model = default_model or os.environ.get(
            "HEXHARNESS_GOOGLE_MODEL", "gemini-2.0-flash"
        )

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        on_text=None,  # ponytail: accepted for the LLMProvider contract; real streaming is a TODO
    ) -> ModelResponse:
        config: dict[str, Any] = {"max_output_tokens": max_tokens}
        if system:
            config["system_instruction"] = system
        if tools:
            config["tools"] = tools_to_genai(tools)
        resp = await self._client.aio.models.generate_content(
            model=model or self.default_model,
            contents=to_genai_contents(messages),
            config=config,
        )
        return from_genai_response(resp)
