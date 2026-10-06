"""TUI tests. Skipped entirely if Textual isn't installed."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Footer, Input, Label, RichLog  # noqa: E402

from hexharness.tui import providers  # noqa: E402
from hexharness.tui.app import HexHeader, HexTUI  # noqa: E402
from hexharness.tui.screens import ProviderScreen  # noqa: E402


# --- pure provider logic (no network, no .complete) ---

def test_detect_reflects_env(monkeypatch):
    anthropic = providers.entry("anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert providers.detect(anthropic) is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
    assert providers.detect(anthropic) is True


def test_detect_ollama_needs_no_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert providers.detect(providers.entry("ollama")) is True  # local, default base_url


def test_build_returns_right_class_and_model(monkeypatch):
    from hexharness.providers.anthropic import AnthropicProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
    prov = providers.build(providers.entry("anthropic"), model="claude-custom")
    assert isinstance(prov, AnthropicProvider)
    assert prov.default_model == "claude-custom"  # override threaded through, no .complete call


def test_register_sets_env_for_process(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    e = providers.entry("openai")
    assert providers.detect(e) is False
    providers.register(e, {"OPENAI_API_KEY": "sk-registered"})
    assert providers.detect(e) is True


# --- app boot + provider screen (Pilot) ---

async def test_app_mounts_core_widgets():
    app = HexTUI()
    async with app.run_test() as pilot:
        assert app.query_one("#header", HexHeader)
        assert app.query_one("#transcript", RichLog)
        assert app.query_one("#prompt", Input)
        assert app.query_one(Footer)
        # header carries the brand + mode
        header_text = str(app.query_one("#header", HexHeader).render())
        assert "HexHarness" in header_text
        assert "interactive/recon" in header_text
        await pilot.pause()


async def test_provider_screen_badges(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = HexTUI()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ProviderScreen)
        configured = str(app.screen.query_one("#prov-anthropic").query_one(Label).render())
        needs = str(app.screen.query_one("#prov-openai").query_one(Label).render())
        assert "●" in configured and "configured" in configured
        assert "○" in needs and "needs key" in needs
