"""OpenAI provider authenticated with a ChatGPT subscription ("Sign in with ChatGPT"
OAuth), not an API key.

HexHarness runs the OAuth login itself (see openai_login) and owns the tokens in its own
data dir — no Codex CLI required. The access token is the bearer against the ChatGPT
backend Responses endpoint (https://chatgpt.com/backend-api/codex/responses), refreshed
in place against auth.openai.com when close to expiry.

All request/response mapping is shared with the API-key OpenAIProvider (Responses API).
Only auth, the base_url, the required headers, and the ChatGPT-specific payload shape
(store=false, stream required, no top-level instructions) differ.
"""
from __future__ import annotations

import os
from typing import Any

from hexharness.providers import openai_login
from hexharness.providers.openai import (
    from_responses_response,
    stream_responses,
    to_responses_input,
    tools_to_responses,
)
from hexharness.providers.openai_login import is_logged_in  # re-exported for the catalog
from hexharness.providers.types import Message, ModelResponse, ToolSpec

_CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"

__all__ = ["OpenAIOAuthProvider", "is_logged_in"]


class OpenAIOAuthProvider:
    """OpenAI via a ChatGPT subscription, using HexHarness's own OAuth tokens. Always
    streams (the ChatGPT backend only returns SSE) and omits max_output_tokens / top-level
    instructions, which that backend does not accept."""

    name = "openai-oauth"

    def __init__(self, *, default_model: str | None = None):
        from openai import AsyncOpenAI  # lazy: package imports without the SDK

        store = openai_login.load_fresh()
        account_id = store.get("account_id") or openai_login.account_id_from(
            store.get("id_token", "")
        )
        self._client = AsyncOpenAI(
            api_key=store["access_token"],
            base_url=_CHATGPT_BASE_URL,
            default_headers={
                "ChatGPT-Account-ID": account_id,
                "originator": "codex_cli_rs",
            },
            max_retries=1,
            timeout=120.0,
        )
        # ponytail: slugs come from ~/.codex/models_cache.json and rotate every few
        # months (today the gpt-5.6-* family); override via env or the TUI model field.
        # Note the ChatGPT backend accepts only account-entitled slugs, NOT api.openai.com
        # names like gpt-5/gpt-4o — those 400 with "not supported ... with a ChatGPT account".
        self.default_model = default_model or os.environ.get(
            "HEXHARNESS_OPENAI_OAUTH_MODEL", "gpt-5.6-sol"
        )
        self._no_reasoning: set[str] = set()

    def _ensure_fresh(self) -> None:
        """Refresh the token if it is near expiry and point the client at the new one.
        # ponytail: re-reads the store each turn; cheap (one JWT exp decode) and keeps a
        # long session alive across the ~7-day token lifetime without recreating the client.
        """
        token = self._client.api_key
        if token and not openai_login._expires_soon(token):
            return
        self._client.api_key = openai_login.load_fresh()["access_token"]

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,  # ponytail: ignored — ChatGPT backend has no max_output_tokens
        on_text=None,
        on_thinking=None,
    ) -> ModelResponse:
        from openai import BadRequestError

        self._ensure_fresh()
        model = model or self.default_model
        # No top-level `instructions` on the ChatGPT backend: the system prompt rides as the
        # first input item (Codex injects its base instructions the same way).
        inp = to_responses_input(messages)
        if system:
            inp.insert(0, {"role": "system", "content": system})
        kwargs: dict[str, Any] = {
            "model": model,
            "input": inp,
            "store": False,  # required false by the ChatGPT backend
        }
        if tools:
            kwargs["tools"] = tools_to_responses(tools)
        if model not in self._no_reasoning:
            kwargs["reasoning"] = {"summary": "auto"}
            kwargs["include"] = ["reasoning.encrypted_content"]

        # Always stream: the backend only returns SSE. A missing sink gets a no-op.
        async def call(kw):
            return await stream_responses(
                self._client, kw, on_text or (lambda s: None), on_thinking
            )

        try:
            return await call(kwargs)
        except BadRequestError as e:
            if "reasoning" not in kwargs or "reasoning" not in str(e).lower():
                raise
            self._no_reasoning.add(model)
            kwargs.pop("reasoning")
            kwargs.pop("include", None)
            return await call(kwargs)
