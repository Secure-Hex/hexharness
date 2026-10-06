"""web_search: backend selection (free ddgs default, paid when a key is present) and
formatting. No network — backends are injected / selection is checked by name."""
from __future__ import annotations

from hexharness.control.vault import Vault
from hexharness.tools.native.websearch import WebSearchTool


def test_defaults_to_duckduckgo_without_keys():
    tool = WebSearchTool(Vault())  # empty vault, no env keys
    name, _ = tool._select_backend()
    assert name == "duckduckgo"


def test_prefers_tavily_then_exa_when_key_present():
    v = Vault()
    v.set("EXA_API_KEY", "exa-k")
    assert WebSearchTool(v)._select_backend()[0] == "exa"
    v.set("TAVILY_API_KEY", "tav-k")  # tavily wins over exa
    assert WebSearchTool(v)._select_backend()[0] == "tavily"


async def test_runs_injected_backend_and_formats():
    def fake(query, k):
        return [{"title": "ACME login", "url": "https://acme.example/login",
                 "snippet": "corporate SSO portal"}][:k]

    tool = WebSearchTool(search_fn=fake)
    out = await tool.run({"query": "acme login", "max_results": 3})
    assert "ACME login" in out and "https://acme.example/login" in out
    assert "injected" in out


async def test_empty_results_message():
    tool = WebSearchTool(search_fn=lambda q, k: [])
    out = await tool.run({"query": "nothing"})
    assert "no results" in out


def test_capabilities_panel_shows_active_backend():
    import pytest
    pytest.importorskip("textual")
    from types import SimpleNamespace
    from hexharness.tui.screens import CapabilitiesScreen

    v = Vault()
    eng = SimpleNamespace(registry=SimpleNamespace(_tools={"web_search": WebSearchTool(v)}), vault=v)
    screen = CapabilitiesScreen(engine=eng, provider="anthropic", model="x")
    assert screen._web_backend() == "duckduckgo"
    v.set("TAVILY_API_KEY", "k")
    assert screen._web_backend() == "tavily"
