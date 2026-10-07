"""Generic OpenAI-compatible provider.

Most hosted LLM gateways (OpenRouter, Groq, Together, DeepSeek, xAI, Mistral,
Fireworks, Perplexity, local vLLM/LM Studio, ...) speak the OpenAI Chat Completions
wire format — only the base_url and api key differ. So they all reuse the OpenAI
adapter's mapping; this class just points AsyncOpenAI at a different base_url. That is
also the "bring your own provider" path: pass any base_url + key at runtime.
"""
from __future__ import annotations

import os
from typing import Any

from hexharness.providers.openai import (
    from_openai_response,
    stream_openai,
    to_openai_messages,
    tools_to_openai,
)
from hexharness.providers.types import Message, ModelResponse, ToolSpec


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        default_model: str,
        name: str = "openai-compatible",
        api_key: str | None = None,
        api_key_env: str | None = None,
    ):
        from openai import AsyncOpenAI  # lazy: package imports without the SDK

        key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        if not key:
            raise RuntimeError(f"{api_key_env or 'api_key'} not set for provider {name!r}")
        self.name = name
        self.default_model = default_model
        # short connect timeout so an unreachable gateway fails fast instead of hanging
        self._client = AsyncOpenAI(api_key=key, base_url=base_url, max_retries=1,
                                   timeout=60.0)

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
