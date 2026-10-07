"""Mode menu (ctrl+o) + custom OpenAI-compatible provider. Skipped if Textual absent."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Label, ListView  # noqa: E402

from hexharness.control.policy import Autonomy, Mode, Phase  # noqa: E402
from hexharness.tui import providers  # noqa: E402
from hexharness.tui.app import HexTUI  # noqa: E402
from hexharness.tui.screens import CustomProviderModal, ModeScreen, ProviderScreen  # noqa: E402


# --- Task A: Mode menu ---

async def test_ctrl_o_sets_mode_in_place_and_preserves_conversation():
    from hexharness.engine import Engine
    from hexharness.providers.types import Message

    app = HexTUI()
    async with app.run_test() as pilot:
        # a real running engine with some conversation history
        app.engine = Engine.from_engagement("tests/data/sample.engagement.yaml", provider=None)
        app.engine.events._bus.subscribe(app._on_event)
        app.loop = app.engine.loop(provider=None)
        app.loop.conversation = [Message.user_text("earlier"), Message.user_text("history")]

        await pilot.press("ctrl+o")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ModeScreen)
        app.screen.query_one("#mode-autonomy", ListView).index = list(Autonomy).index(Autonomy.AUTO)
        app.screen.query_one("#mode-phase", ListView).index = list(Phase).index(Phase.EXPLOITATION)
        app.screen.action_submit()
        await pilot.pause()
        await pilot.pause()

        assert app.mode.autonomy is Autonomy.AUTO  # requested mode recorded
        assert app.engine is not None              # NOT rebuilt — in place
        assert len(app.loop.conversation) == 2     # conversation preserved
        # ctx mode is the ROE-clamped effective mode (fixture caps autonomy at interactive)
        assert app.loop.ctx is app.engine.ctx


# --- Task B: provider screen lists the openai_compatible gateways ---

async def test_provider_screen_lists_openai_compatible_gateways():
    app = HexTUI()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, ProviderScreen)
        text = "\n".join(str(w.render()) for w in app.screen.query(Label))
        assert "OpenRouter" in text and "Groq" in text


# --- Task B: custom modal shape + masked key ---

async def test_custom_modal_returns_selection_shape_with_masked_key():
    app = HexTUI()
    async with app.run_test() as pilot:
        results: list[dict | None] = []
        modal = CustomProviderModal()
        await app.push_screen(modal, results.append)
        await pilot.pause()

        key_input = modal.query_one("#custom-api-key", Input)
        assert key_input.password is True  # MASKED

        modal.query_one("#custom-name", Input).value = "my-gw"
        modal.query_one("#custom-base-url", Input).value = "https://gw/v1"
        modal.query_one("#custom-model", Input).value = "my-model"
        key_input.value = "sk-local-only"
        modal.action_submit()
        await pilot.pause()

        assert results == [{
            "kind": "custom",
            "params": {
                "name": "my-gw",
                "base_url": "https://gw/v1",
                "model": "my-model",
                "api_key": "sk-local-only",
            },
        }]


def test_make_provider_custom_calls_build_custom(monkeypatch):
    called: dict = {}

    def sentinel(**kwargs):
        called.update(kwargs)
        return "CUSTOM_PROVIDER"

    monkeypatch.setattr(providers, "build_custom", sentinel)
    app = HexTUI()
    app._selection = {
        "kind": "custom",
        "params": {"name": "gw", "base_url": "https://gw/v1", "model": "m", "api_key": "sk-x"},
    }
    assert app._make_provider() == "CUSTOM_PROVIDER"
    assert called == {"name": "gw", "base_url": "https://gw/v1", "model": "m", "api_key": "sk-x"}
    assert app._model_override() == "m"  # custom model threaded through
