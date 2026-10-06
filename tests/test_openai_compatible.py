"""OpenAI-compatible gateways (OpenRouter, Groq, ...) and bring-your-own provider."""
from __future__ import annotations

import pytest

from hexharness.tui.providers import CATALOG, build, build_custom, entry


def test_known_gateways_in_catalog_with_base_urls():
    keys = {e.key for e in CATALOG}
    assert {"openrouter", "groq", "together", "deepseek", "xai", "mistral", "fireworks", "perplexity"} <= keys
    assert entry("openrouter").base_url == "https://openrouter.ai/api/v1"
    assert entry("groq").base_url == "https://api.groq.com/openai/v1"
    assert all(e.kind == "openai_compatible" for e in CATALOG if e.key in {"openrouter", "groq"})


def test_build_openai_compatible_uses_base_url(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    prov = build(entry("openrouter"), model="anthropic/claude-3.5-sonnet")
    assert prov.name == "openrouter"
    assert prov.default_model == "anthropic/claude-3.5-sonnet"
    assert str(prov._client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


def test_build_custom_provider(monkeypatch):
    pytest.importorskip("openai")
    prov = build_custom(name="my-gw", base_url="https://gw.local/v1", api_key="sk-x", model="my-model")
    assert prov.name == "my-gw" and prov.default_model == "my-model"
    assert str(prov._client.base_url).rstrip("/") == "https://gw.local/v1"


def test_missing_key_raises(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        build(entry("groq"))
