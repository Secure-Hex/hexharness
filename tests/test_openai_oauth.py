"""OpenAIOAuthProvider: ChatGPT-subscription auth via Codex tokens. Verifies the
ChatGPT-backend request shape (store=false, always streamed, no max_output_tokens, no
top-level instructions, system as first input item) and in-place token refresh. Fake
client and fake httpx — no network, no real ~/.codex."""
from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("openai")

from hexharness.providers import openai_oauth as mod  # noqa: E402
from hexharness.providers.types import Message, StopReason  # noqa: E402


def _jwt(exp: float, extra: dict | None = None) -> str:
    payload = {"exp": exp, "client_id": "app_test", **(extra or {})}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.sig"


def _auth_file(tmp_path, monkeypatch, *, exp: float, refresh="rt-1"):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    data = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": _jwt(exp),
            "access_token": _jwt(exp),
            "refresh_token": refresh,
            "account_id": "acct-xyz",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    (tmp_path / "auth.json").write_text(json.dumps(data))
    return data


def _msg(text):
    return SimpleNamespace(type="message", content=[SimpleNamespace(type="output_text", text=text)])


def _resp(output):
    return SimpleNamespace(
        output=output, status="completed", incomplete_details=None,
        usage=SimpleNamespace(input_tokens=5, output_tokens=2), model="gpt-5-codex",
    )


class _FakeResponses:
    def __init__(self, events):
        self.events, self.calls = events, []

    async def create(self, **kw):
        self.calls.append(kw)

        async def gen():
            for e in self.events:
                yield e
        return gen()


def _provider(tmp_path, monkeypatch, fake):
    p = mod.OpenAIOAuthProvider()
    p._client = SimpleNamespace(responses=fake, api_key=p._client.api_key)
    return p


async def test_chatgpt_request_shape(tmp_path, monkeypatch):
    _auth_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    fake = _FakeResponses([SimpleNamespace(type="response.completed", response=_resp([_msg("ok")]))])
    p = _provider(tmp_path, monkeypatch, fake)

    r = await p.complete([Message.user_text("hola")], system="sys", max_tokens=999)

    assert r.text() == "ok" and r.stop_reason is StopReason.END_TURN
    kw = fake.calls[0]
    assert kw["stream"] is True                      # backend is SSE-only
    assert kw["store"] is False                       # required false
    assert "max_output_tokens" not in kw              # backend rejects it
    assert "instructions" not in kw                   # no top-level instructions
    assert kw["input"][0] == {"role": "system", "content": "sys"}  # system rides in input
    assert kw["include"] == ["reasoning.encrypted_content"]


def test_refresh_writes_back_when_expired(tmp_path, monkeypatch):
    _auth_file(tmp_path, monkeypatch, exp=time.time() - 10)  # already expired
    new_access = _jwt(time.time() + 100_000)
    posted = {}

    def fake_post(url, json=None, timeout=None):
        posted["url"], posted["body"] = url, json
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"access_token": new_access, "refresh_token": "rt-2"},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    data = mod._load_fresh()

    assert posted["url"] == "https://auth.openai.com/oauth/token"
    assert posted["body"]["grant_type"] == "refresh_token"
    assert posted["body"]["refresh_token"] == "rt-1"
    assert data["tokens"]["access_token"] == new_access
    # persisted to disk, other keys preserved, refresh token rotated
    on_disk = json.loads((tmp_path / "auth.json").read_text())
    assert on_disk["tokens"]["access_token"] == new_access
    assert on_disk["tokens"]["refresh_token"] == "rt-2"
    assert on_disk["OPENAI_API_KEY"] is None
    assert on_disk["last_refresh"] != "2026-01-01T00:00:00Z"


def test_is_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert mod.is_logged_in() is False
    _auth_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    assert mod.is_logged_in() is True
