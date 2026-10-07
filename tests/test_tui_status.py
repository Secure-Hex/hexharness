"""Status line and live thinking pane react to model reasoning and run lifecycle."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Static

from hexharness.tui.app import HexTUI


async def test_thinking_updates_status_and_pane():
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert "ready" in str(app.query_one("#status", Static).render())
        app._stream_thinking("weighing the scope")
        await pilot.pause()
        assert "thinking" in str(app.query_one("#status", Static).render())
        assert "weighing the scope" in str(app.query_one("#thinking", Static).render())
        app._flush_live()  # end of turn clears the thinking pane
        assert str(app.query_one("#thinking", Static).render()) == ""
