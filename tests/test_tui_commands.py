"""The commands side panel (Ctrl+B) toggles and lists the shortcuts; the footer no
longer carries the full keybind list."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import Static

from hexharness.tui.app import HexTUI


async def test_command_panel_toggles_and_lists():
    app = HexTUI()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        panel = app.query_one("#command-panel", Static)
        assert panel.display is False               # hidden by default
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert panel.display is True
        text = str(panel.render())
        assert "Edit engagement" in text and "Findings" in text and "/compact" in text
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert panel.display is False               # toggles back off


def test_footer_bindings_mostly_hidden():
    # only the Commands toggle is shown in the footer; everything else lives in the panel
    shown = [b for b in HexTUI.BINDINGS if getattr(b, "show", True)]
    assert [b.action for b in shown] == ["commands"]
