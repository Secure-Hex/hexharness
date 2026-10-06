"""Out-of-band secret flow: missing secret => operator is asked; value goes to the
Vault, never to the model or the audit log; cancel => fail-closed deny."""
from __future__ import annotations

from hexharness.control.secrets import CallbackSecretRequester, DenySecretRequester
from hexharness.control.vault import Vault
from hexharness.events.types import EventType
from hexharness.tools.base import RiskLevel

from tests._fakes import SpyTool
from tests.conftest import ctx, make_control
from hexharness.control.policy import Mode


def _tool_needing(secret: str) -> SpyTool:
    t = SpyTool("shodan_query", RiskLevel.PASSIVE)
    t.required_secrets = [secret]
    return t


async def test_missing_secret_prompts_and_stores(monkeypatch):
    cp, events = make_control()
    cp.vault = Vault()
    cp.secret_requester = CallbackSecretRequester(lambda name, reason: "sk-topsecret")
    tool = _tool_needing("SHODAN_API_KEY")

    d = await cp.authorize(ctx(Mode()), tool, {})
    assert d.allowed
    assert cp.vault.get("SHODAN_API_KEY") == "sk-topsecret"

    # the SECRET VALUE must never appear in any event payload — only its name may.
    blob = str([e.payload for e in events.all()])
    assert "sk-topsecret" not in blob
    assert "SHODAN_API_KEY" in blob


async def test_cancel_denies_fail_closed():
    cp, events = make_control()
    cp.vault = Vault()
    cp.secret_requester = DenySecretRequester()
    d = await cp.authorize(ctx(Mode()), _tool_needing("SHODAN_API_KEY"), {})
    assert d.effect.value == "deny"
    assert d.gate == "secrets"


async def test_present_secret_is_not_reprompted():
    cp, events = make_control()
    cp.vault = Vault()
    cp.vault.set("SHODAN_API_KEY", "already-here")
    calls = []
    cp.secret_requester = CallbackSecretRequester(lambda name, reason: calls.append(name) or "x")
    d = await cp.authorize(ctx(Mode()), _tool_needing("SHODAN_API_KEY"), {})
    assert d.allowed and calls == []  # vault already had it => no prompt


def test_vault_names_never_leak_values():
    v = Vault()
    v.set("MY_API_KEY", "supersecret")
    assert "MY_API_KEY" in v.names()
    assert "supersecret" not in v.names()
    assert v.redact("token is supersecret done") == "token is ***REDACTED*** done"
