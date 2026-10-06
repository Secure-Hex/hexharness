"""Ollama / vLLM adapter via the OpenAI-compatible HTTP endpoint.

Local model, no cloud key. base_url from env OLLAMA_BASE_URL (default
http://localhost:11434/v1). Reuses the OpenAI Chat Completions mapping helpers since
the wire format is identical.
"""
from __future__ import annotations

import os
from typing import Any

from hexharness.providers.openai import (
    from_openai_response,
    to_openai_messages,
    tools_to_openai,
)
from hexharness.providers.types import Message, ModelResponse, ToolSpec

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, base_url: str | None = None, default_model: str | None = None):
        # Imported lazily so the package imports without the SDK installed.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
            api_key="ollama",  # ponytail: local endpoint ignores the key but the SDK requires one.
        )
        self.default_model = default_model or os.environ.get("HEXHARNESS_OLLAMA_MODEL", "llama3.1")

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "messages": to_openai_messages(messages, system),
        }
        if tools:
            kwargs["tools"] = tools_to_openai(tools)
        resp = await self._client.chat.completions.create(**kwargs)
        return from_openai_response(resp)
