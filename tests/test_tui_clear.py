"""TUI: /clear forgets the model conversation but keeps the engine (engagement/scope/findings)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from hexharness.providers.types import Message
from hexharness.tui.app import HexTUI


async def test_clear_resets_conversation_and_keeps_engine():
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        engine = app.engine
        app.loop = SimpleNamespace(conversation=[Message.user_text("hi")], last_input_tokens=42)
        app._saved_conversation = [Message.user_text("pending")]

        app._clear_conversation()

        assert app.loop.conversation == []
        assert app.loop.last_input_tokens == 0
        assert app._saved_conversation is None
        assert app.engine is engine


async def test_clear_refused_while_turn_running():
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.loop = SimpleNamespace(conversation=[Message.user_text("hi")], last_input_tokens=42)
        app._turn_running = True

        app._clear_conversation()

        assert len(app.loop.conversation) == 1
