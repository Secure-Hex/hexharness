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


async def test_cancel_aborts_and_clears_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("HEXHARNESS_CONFIG", str(tmp_path / "cfg.json"))
    from types import SimpleNamespace
    from hexharness.providers.types import Message

    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        cancelled = {"n": 0}
        app._run_worker = SimpleNamespace(cancel=lambda: cancelled.__setitem__("n", 1))
        app.loop = SimpleNamespace(conversation=[Message.user_text("stuck question")])
        app._queue = ["one", "two"]
        app._running = True

        app.action_cancel()
        assert cancelled["n"] == 1          # the stuck worker was cancelled
        assert app._queue == []             # queue cleared
        assert app._running is False        # recovered
        assert app.loop.conversation == []  # trailing unanswered user msg dropped
