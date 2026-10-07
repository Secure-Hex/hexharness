"""Provider selection persists across sessions; API keys are never written to disk."""
from __future__ import annotations

from hexharness.tui.config import load_selection, save_selection


def test_roundtrip_named_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "config.json"))
    save_selection({"kind": "provider", "keys": ["openai"], "model": "gpt-4o"})
    assert load_selection() == {"kind": "provider", "keys": ["openai"], "model": "gpt-4o"}


def test_custom_provider_key_never_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "config.json"))
    save_selection({"kind": "custom", "params": {
        "name": "mygw", "base_url": "https://gw.local/v1", "model": "m", "api_key": "sk-SECRET"}})
    loaded = load_selection()
    assert loaded["params"]["base_url"] == "https://gw.local/v1"
    assert "api_key" not in loaded["params"]           # stripped
    assert "sk-SECRET" not in (tmp_path / "config.json").read_text()  # not on disk anywhere


def test_missing_config_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "nope.json"))
    assert load_selection() is None


def test_mode_roundtrips(tmp_path, monkeypatch):
    from hexharness.tui.config import load_mode, save_mode
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "config.json"))
    save_mode("bypass", "exploitation")
    assert load_mode() == {"autonomy": "bypass", "phase": "exploitation"}
