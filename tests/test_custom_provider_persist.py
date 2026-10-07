"""Custom (bring-your-own) providers persist globally across sessions.

The api_key IS stored on disk (like OpenCode/aider) so a saved gateway reloads fully
usable, but only in a 0600 secret store separate from the non-secret selection config.
"""
from __future__ import annotations

import os

import pytest

from hexharness.tui import providers
from hexharness.tui.config import (
    load_custom_providers,
    providers_store_path,
    save_custom_provider,
)


def _use_tmp_store(tmp_path, monkeypatch):
    store = tmp_path / "providers.json"
    monkeypatch.setenv("HEXHARNESS_PROVIDERS", str(store))
    return store


def test_roundtrip_persists_api_key(tmp_path, monkeypatch):
    store = _use_tmp_store(tmp_path, monkeypatch)
    entry = {"name": "mygw", "base_url": "https://gw.local/v1", "model": "m", "api_key": "sk-SECRET"}
    save_custom_provider(entry)
    assert load_custom_providers() == [entry]
    assert "sk-SECRET" in store.read_text()  # key IS stored (deliberate reuse)


def test_store_is_0600(tmp_path, monkeypatch):
    store = _use_tmp_store(tmp_path, monkeypatch)
    save_custom_provider({"name": "mygw", "base_url": "https://gw.local/v1", "model": "m", "api_key": "k"})
    assert os.stat(store).st_mode & 0o777 == 0o600


def test_dedup_by_name(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    save_custom_provider({"name": "gw", "base_url": "a", "model": "m1", "api_key": "k1"})
    save_custom_provider({"name": "gw", "base_url": "b", "model": "m2", "api_key": "k2"})
    saved = load_custom_providers()
    assert len(saved) == 1
    assert saved[0]["base_url"] == "b" and saved[0]["api_key"] == "k2"


def test_entries_and_entry_resolve(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    save_custom_provider({"name": "My GW", "base_url": "https://gw.local/v1", "model": "m", "api_key": "k"})
    # name "My GW" slugs to "my_gw"
    e = providers.entry("custom:my_gw")
    assert e in providers.all_entries()
    assert e.kind == "openai_compatible"
    assert e.base_url == "https://gw.local/v1"
    assert e.required_env == ()  # key is in the store, not the env


def test_detect_always_true_for_saved_custom(tmp_path, monkeypatch):
    _use_tmp_store(tmp_path, monkeypatch)
    save_custom_provider({"name": "gw", "base_url": "https://gw.local/v1", "model": "m", "api_key": "k"})
    assert providers.detect(providers.entry("custom:gw")) is True


def test_build_uses_stored_key_no_env(tmp_path, monkeypatch):
    pytest.importorskip("openai")
    _use_tmp_store(tmp_path, monkeypatch)
    # No env var set at all — the stored key must be enough.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    save_custom_provider({"name": "gw", "base_url": "https://gw.local/v1", "model": "m", "api_key": "sk-stored"})
    from hexharness.providers.openai_compatible import OpenAICompatibleProvider

    provider = providers.build(providers.entry("custom:gw"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._client.base_url.__str__().rstrip("/") == "https://gw.local/v1"
