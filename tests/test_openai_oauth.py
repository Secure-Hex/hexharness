"""OpenAI ChatGPT-subscription auth: native OAuth login (openai_login) + the
OpenAIOAuthProvider request shape. Verifies the ChatGPT-backend request shape (store=false,
always streamed, no max_output_tokens, no top-level instructions, system as first input
item), PKCE/authorize-url building, the token store, and in-place refresh. Fake client and
fake httpx — no network, no browser, no real credentials."""
from __future__ import annotations

import base64
import hashlib
import json
import stat
import time
from types import SimpleNamespace

import httpx
import pytest

from hexharness.providers import openai_login as L  # noqa: E402


def _jwt(exp: float, extra: dict | None = None) -> str:
    payload = {"exp": exp, **(extra or {})}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.sig"


def _store_file(tmp_path, monkeypatch, *, exp: float, refresh="rt-1") -> dict:
    monkeypatch.setenv("HEXHARNESS_OPENAI_AUTH", str(tmp_path / "openai_oauth.json"))
    store = {
        "access_token": _jwt(exp),
        "refresh_token": refresh,
        "id_token": _jwt(exp, {"https://api.openai.com/auth": {"chatgpt_account_id": "acct-xyz"}}),
        "account_id": "acct-xyz",
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    L._write(store)
    return store


# ------------------------------------------------------------------ login module --
def test_pkce_is_s256():
    v, c = L._pkce()
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def test_authorize_url_has_required_params():
    u = L.authorize_url("CHAL", "STATE")
    for frag in ("response_type=code", "code_challenge=CHAL", "code_challenge_method=S256",
                 "state=STATE", L.CLIENT_ID, "offline_access", "codex_cli_simplified_flow=true"):
        assert frag in u


def test_parse_redirect_forms():
    assert L.parse_redirect("http://localhost:1455/auth/callback?code=abc&state=xy") == {
        "code": "abc", "state": "xy"}
    assert L.parse_redirect("abc#xy") == {"code": "abc", "state": "xy"}
    assert L.parse_redirect("rawcode") == {"code": "rawcode"}
    assert L.parse_redirect("") == {}


def test_account_id_from_id_token():
    tok = _jwt(time.time(), {"https://api.openai.com/auth": {"chatgpt_account_id": "acc-1"}})
    assert L.account_id_from(tok) == "acc-1"
    assert L.account_id_from("garbage") == ""


def test_store_written_0600(tmp_path, monkeypatch):
    _store_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    mode = stat.S_IMODE((tmp_path / "openai_oauth.json").stat().st_mode)
    assert mode == 0o600


def test_is_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_OPENAI_AUTH", str(tmp_path / "openai_oauth.json"))
    assert L.is_logged_in() is False
    _store_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    assert L.is_logged_in() is True


def test_exchange_code_posts_form_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_OPENAI_AUTH", str(tmp_path / "openai_oauth.json"))
    new_access = _jwt(time.time() + 100_000)
    id_token = _jwt(time.time(), {"https://api.openai.com/auth": {"chatgpt_account_id": "acc-9"}})
    posted = {}

    def fake_post(url, data=None, timeout=None):
        posted["url"], posted["data"] = url, data
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"access_token": new_access, "refresh_token": "rt-9",
                                             "id_token": id_token})

    monkeypatch.setattr(httpx, "post", fake_post)
    store = L.exchange_code("the-code", "the-verifier")

    assert posted["url"] == "https://auth.openai.com/oauth/token"
    assert posted["data"]["grant_type"] == "authorization_code"
    assert posted["data"]["code"] == "the-code"
    assert posted["data"]["code_verifier"] == "the-verifier"
    assert store["access_token"] == new_access and store["account_id"] == "acc-9"
    on_disk = json.loads((tmp_path / "openai_oauth.json").read_text())
    assert on_disk["refresh_token"] == "rt-9"


def test_refresh_writes_back_when_expired(tmp_path, monkeypatch):
    _store_file(tmp_path, monkeypatch, exp=time.time() - 10)  # already expired
    new_access = _jwt(time.time() + 100_000)
    posted = {}

    def fake_post(url, data=None, timeout=None):
        posted["url"], posted["data"] = url, data
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"access_token": new_access, "refresh_token": "rt-2"})

    monkeypatch.setattr(httpx, "post", fake_post)
    store = L.load_fresh()

    assert posted["data"]["grant_type"] == "refresh_token"
    assert posted["data"]["refresh_token"] == "rt-1"
    assert posted["data"]["client_id"] == L.CLIENT_ID
    assert store["access_token"] == new_access
    on_disk = json.loads((tmp_path / "openai_oauth.json").read_text())
    assert on_disk["access_token"] == new_access and on_disk["refresh_token"] == "rt-2"
    assert on_disk["last_refresh"] != "2026-01-01T00:00:00Z"


def test_manual_login_exchanges_pasted_code(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_OPENAI_AUTH", str(tmp_path / "openai_oauth.json"))
    monkeypatch.setattr("builtins.input", lambda *a: "pasted-code")
    monkeypatch.setattr(L, "exchange_code", lambda code, verifier: {"access_token": "A", "code": code})
    store = L.login(manual=True)
    assert store == {"access_token": "A", "code": "pasted-code"}


def test_logout(tmp_path, monkeypatch):
    _store_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    assert L.logout() is True
    assert L.logout() is False  # already gone


# ------------------------------------------------------------------ provider --
pytest.importorskip("openai")
from hexharness.providers import openai_oauth as mod  # noqa: E402
from hexharness.providers.types import Message, StopReason  # noqa: E402


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


async def test_chatgpt_request_shape(tmp_path, monkeypatch):
    _store_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    fake = _FakeResponses([SimpleNamespace(type="response.completed", response=_resp([_msg("ok")]))])
    p = mod.OpenAIOAuthProvider()
    p._client = SimpleNamespace(responses=fake, api_key=p._client.api_key)

    r = await p.complete([Message.user_text("hola")], system="sys", max_tokens=999)

    assert r.text() == "ok" and r.stop_reason is StopReason.END_TURN
    kw = fake.calls[0]
    assert kw["stream"] is True                      # backend is SSE-only
    assert kw["store"] is False                      # required false
    assert "max_output_tokens" not in kw             # backend rejects it
    assert "instructions" not in kw                  # no top-level instructions
    assert kw["input"][0] == {"role": "system", "content": "sys"}  # system rides in input
    assert kw["include"] == ["reasoning.encrypted_content"]


def test_provider_is_logged_in_reexport(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_OPENAI_AUTH", str(tmp_path / "openai_oauth.json"))
    assert mod.is_logged_in() is False
    _store_file(tmp_path, monkeypatch, exp=time.time() + 100_000)
    assert mod.is_logged_in() is True
