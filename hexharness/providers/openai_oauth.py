"""OpenAI provider authenticated with a ChatGPT subscription (Codex "Sign in with
ChatGPT" OAuth), not an API key.

It reuses the credentials the Codex CLI already wrote to ~/.codex/auth.json: the
access token is used as the bearer against the ChatGPT backend Responses endpoint
(https://chatgpt.com/backend-api/codex/responses), and refreshed in place against
auth.openai.com when it is close to expiry. Codex owns the login flow; we borrow and
refresh the token.

All request/response mapping is shared with the API-key OpenAIProvider (Responses API).
Only auth, the base_url, the required headers, and the ChatGPT-specific payload shape
(store=false, stream required, no top-level instructions) differ.

Constants (client_id, endpoints, headers, payload rules) are taken from the open-source
openai/codex `codex-rs` crates; the client_id is read from the token itself when present,
falling back to the published default.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from hexharness.providers.openai import (
    from_responses_response,
    stream_responses,
    to_responses_input,
    tools_to_responses,
)
from hexharness.providers.types import Message, ModelResponse, ToolSpec

_ISSUER = "https://auth.openai.com"
_TOKEN_URL = f"{_ISSUER}/oauth/token"
_CHATGPT_BASE_URL = "https://chatgpt.com/backend-api/codex"
_DEFAULT_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_REFRESH_SKEW = 300  # refresh when the access token expires within this many seconds


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def auth_path() -> Path:
    return _codex_home() / "auth.json"


def is_logged_in() -> bool:
    """True when a Codex auth.json with ChatGPT tokens exists — used by the TUI to decide
    whether to offer this provider."""
    try:
        data = json.loads(auth_path().read_text())
    except (OSError, ValueError):
        return False
    return bool((data.get("tokens") or {}).get("access_token"))


def _jwt_claims(jwt: str) -> dict[str, Any]:
    """Decode a JWT payload without verifying the signature. These tokens are OpenAI's; we
    only read public claims (exp, client_id) to drive refresh — we never trust them for auth."""
    try:
        seg = jwt.split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except (IndexError, ValueError):
        return {}


def _expires_soon(access_token: str) -> bool:
    exp = _jwt_claims(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True  # can't tell — refresh to be safe
    return time.time() + _REFRESH_SKEW >= exp


def _write_auth(data: dict[str, Any]) -> None:
    """Rewrite auth.json preserving every other key, with 0600 perms, atomically."""
    p = auth_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _refresh(data: dict[str, Any]) -> dict[str, Any]:
    """Exchange the refresh token for a fresh access token and persist it back into
    auth.json. Mirrors Codex: JSON body, no scope/resource, refresh_reason set."""
    import httpx

    tokens = data.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "Codex auth.json has no refresh_token; run `codex login` to re-authenticate"
        )
    client_id = _jwt_claims(tokens.get("access_token", "")).get("client_id") or _DEFAULT_CLIENT_ID
    resp = httpx.post(
        _TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            "refresh_reason": "proactive_expiry",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    body = resp.json()
    for field in ("id_token", "access_token", "refresh_token"):
        if body.get(field):
            tokens[field] = body[field]
    data["tokens"] = tokens
    data["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_auth(data)
    return data


def _load_fresh() -> dict[str, Any]:
    """Load auth.json, refreshing the access token first if it is close to expiry."""
    try:
        data = json.loads(auth_path().read_text())
    except (OSError, ValueError) as e:
        raise RuntimeError(
            f"no usable Codex credentials at {auth_path()}; run `codex login` first"
        ) from e
    token = (data.get("tokens") or {}).get("access_token")
    if not token:
        raise RuntimeError(f"{auth_path()} has no access_token; run `codex login` first")
    if _expires_soon(token):
        data = _refresh(data)
    return data


class OpenAIOAuthProvider:
    """OpenAI via a ChatGPT subscription, using Codex's OAuth tokens. Always streams
    (the ChatGPT backend only returns SSE) and omits max_output_tokens / top-level
    instructions, which that backend does not accept."""

    name = "openai-oauth"

    def __init__(self, *, default_model: str | None = None):
        from openai import AsyncOpenAI  # lazy: package imports without the SDK

        data = _load_fresh()
        tokens = data["tokens"]
        account_id = tokens.get("account_id") or _jwt_claims(
            tokens.get("id_token", "")
        ).get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")
        self._client = AsyncOpenAI(
            api_key=tokens["access_token"],
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
        # ponytail: re-reads auth.json each turn; cheap (one JWT exp decode) and keeps a
        # long session alive across the ~7-day token lifetime without recreating the client.
        """
        token = self._client.api_key
        if token and not _expires_soon(token):
            return
        self._client.api_key = _load_fresh()["tokens"]["access_token"]

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
