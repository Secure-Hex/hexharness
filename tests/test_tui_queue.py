"""Typing while a turn runs queues the message instead of being blocked."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from hexharness.tui.app import HexTUI
from hexharness.tui.widgets import PromptArea


async def test_submit_while_running_queues(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "cfg.json"))
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._running = True                     # pretend a turn is in flight
        box = app.query_one("#prompt", PromptArea)
        box.post_message(PromptArea.Submitted("queued one"))
        await pilot.pause()
        box.post_message(PromptArea.Submitted("queued two"))
        await pilot.pause()
        assert app._queue == ["queued one", "queued two"]
        # input stays usable (not disabled) so the operator can keep typing
        assert box.disabled is False
