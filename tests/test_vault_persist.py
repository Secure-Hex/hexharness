"""Encrypted-at-rest persistence for the Vault: round-trip across instances, 0600 key
perms, and graceful degradation when cryptography is missing (never write plaintext)."""
from __future__ import annotations

import stat

import hexharness.control.vault as vault_mod
from hexharness.control.vault import Vault


def test_roundtrip_across_instances(tmp_path):
    p = tmp_path / "vault.enc"
    v1 = Vault(persist_path=p)
    assert v1.persistence_available()
    v1.set("SHODAN_API_KEY", "sk-topsecret")

    v2 = Vault(persist_path=p)  # fresh instance, same path
    assert v2.get("SHODAN_API_KEY") == "sk-topsecret"
    # names stay names-only; the value never appears
    assert "SHODAN_API_KEY" in v2.names() and "sk-topsecret" not in v2.names()


def test_at_rest_is_not_plaintext(tmp_path):
    p = tmp_path / "vault.enc"
    Vault(persist_path=p).set("SHODAN_API_KEY", "sk-topsecret")
    assert b"sk-topsecret" not in p.read_bytes()


def test_key_file_is_0600(tmp_path):
    p = tmp_path / "vault.enc"
    Vault(persist_path=p).set("K", "v")
    key = p.with_name("vault.key")
    assert key.exists()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_no_crypto_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(vault_mod, "_get_fernet", lambda: None)
    p = tmp_path / "vault.enc"
    v = Vault(persist_path=p)
    assert not v.persistence_available()
    v.set("SHODAN_API_KEY", "sk-topsecret")
    # still works in-process
    assert v.get("SHODAN_API_KEY") == "sk-topsecret"
    # but NOTHING was written to disk (no plaintext leak)
    assert not p.exists()


def test_default_is_memory_only(tmp_path):
    v = Vault()  # back-compat: no path => no persistence, no files
    assert not v.persistence_available()
    v.set("K", "v")
    assert v.get("K") == "v"
