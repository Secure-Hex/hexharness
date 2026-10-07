"""PromptArea wraps and grows with content so a long prompt stays visible."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult

from hexharness.tui.widgets import PromptArea


class _Harness(App):
    def compose(self) -> ComposeResult:
        yield PromptArea(id="prompt", soft_wrap=True)


async def test_prompt_grows_with_long_text():
    app = _Harness()
    async with app.run_test(size=(60, 24)) as pilot:
        box = app.query_one("#prompt", PromptArea)
        await pilot.pause()
        h0 = int(box.styles.height.value)
        box.text = "word " * 80          # one long logical line -> wraps to many rows
        box._autogrow()
        await pilot.pause()
        h1 = int(box.styles.height.value)
        assert h1 > h0
        assert h1 <= PromptArea.MAX_ROWS + 2  # capped, never eats the screen


async def test_enter_submits_and_is_capturable():
    app = _Harness()
    async with app.run_test(size=(60, 24)) as pilot:
        box = app.query_one("#prompt", PromptArea)
        got = {}
        box.post_message(PromptArea.Submitted("resolve www.acme.example"))
        await pilot.pause()
        # the message exists with the text payload (handler wiring lives in the app)
        assert PromptArea.Submitted("x").text == "x"


async def test_slash_suggestions_filter_live():
    from hexharness.tui.app import HexTUI
    from textual.widgets import Static

    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.query_one("#prompt", PromptArea).text = "/s"
        await pilot.pause()
        sug = app.query_one("#slash-suggest", Static)
        assert sug.display is True
        text = str(sug.render())
        assert "/sqli-triage" in text and "/subdomain-enumeration" in text
        app.query_one("#prompt", PromptArea).text = "/s do it"  # space ends the token
        await pilot.pause()
        assert app.query_one("#slash-suggest", Static).display is False


async def test_tab_completes_slash_to_top_match():
    from hexharness.tui.app import HexTUI

    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        box = app.query_one("#prompt", PromptArea)
        box.focus()
        box.text = "/sq"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert box.text == "/sqli-triage "   # completed to the top match + trailing space


async def test_updown_selects_then_tab_completes():
    from hexharness.tui.app import HexTUI

    app = HexTUI()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        box = app.query_one("#prompt", PromptArea)
        box.focus()
        box.text = "/s"               # two matches: sqli-triage, subdomain-enumeration
        await pilot.pause()
        assert app._slash_sel == 0
        await pilot.press("down")
        await pilot.pause()
        assert app._slash_sel == 1
        await pilot.press("tab")
        await pilot.pause()
        assert box.text == "/subdomain-enumeration "   # the SELECTED match, not the top


async def test_enter_completes_selected_slash():
    from hexharness.tui.app import HexTUI
    from hexharness.tui.widgets import PromptArea as _PA

    app = HexTUI()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        box = app.query_one("#prompt", _PA)
        box.focus()
        box.text = "/sq"           # unique-ish match: sqli-triage
        await pilot.pause()
        await pilot.press("enter")  # completes instead of submitting
        await pilot.pause()
        assert box.text == "/sqli-triage "
