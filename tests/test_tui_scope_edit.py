"""TUI: the manual scope editor edits scope directly (no model), then persists + applies."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import Label

from hexharness.engagement import Engagement
from hexharness.engine import Engine
from hexharness.events.types import EventType
from hexharness.tui.app import HexTUI
from hexharness.tui.screens import ScopeEditScreen

EXAMPLE = "tests/data/sample.engagement.yaml"


def _temp_engagement() -> str:
    """A throwaway copy so persisting the edited scope never clobbers the repo file."""
    dst = Path(tempfile.mkdtemp()) / "example.engagement.yaml"
    shutil.copy(EXAMPLE, dst)
    return str(dst)


async def test_edit_applies_and_persists_scope():
    app = HexTUI(engagement=_temp_engagement())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement(EXAMPLE, provider=None)

        async def edit(screen):
            return {"scope": {"domains": ["new.example"], "cidrs": [], "exclusions": []}, "roe": {"max_risk": "active", "max_autonomy": "interactive", "max_phase": "enumeration"}}

        app.push_screen_wait = edit

        await app.action_edit_scope().wait()

        guard = app.engine.control.scope_guard
        assert guard.in_scope("new.example") is True
        assert guard.in_scope("acme.example") is False  # old domain gone
        assert any(e.type is EventType.SCOPE_CHANGED for e in app.engine.events.all())
        # persisted copy survives a reload
        assert Engagement.load(app.engagement_path).scope.domains == ["new.example"]


async def test_editor_renders_current_entries():
    eng = Engagement.load(EXAMPLE)
    app = HexTUI()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(ScopeEditScreen(engagement=eng))
        await pilot.pause()
        labels = [str(w.render()) for w in app.screen.query(Label)]
        assert any("acme.example" in t for t in labels)
        assert any("203.0.113.0/24" in t for t in labels)


async def test_invalid_cidr_not_applied():
    app = HexTUI(engagement=_temp_engagement())
    logs: list[str] = []
    app._log = lambda text, style=None: logs.append(text)  # type: ignore[assignment]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement(EXAMPLE, provider=None)
        before = list(app.engine.engagement.scope.cidrs)

        async def edit(screen):
            return {"scope": {"domains": ["acme.example"], "cidrs": ["not-a-cidr"], "exclusions": []}, "roe": {"max_risk": "active", "max_autonomy": "interactive", "max_phase": "enumeration"}}

        app.push_screen_wait = edit

        await app.action_edit_scope().wait()

        assert app.engine.engagement.scope.cidrs == before  # unchanged
        assert not any(e.type is EventType.SCOPE_CHANGED for e in app.engine.events.all())
        assert any("invalid scope" in t.lower() for t in logs)


async def test_add_entry_no_duplicate_id_crash():
    """Regression: adding a scope entry used to crash with DuplicateIds because
    ListView.clear() is async and items were re-added with fixed ids before removal."""
    import pytest
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Input, ListView
    from hexharness.engagement import Engagement
    from hexharness.tui.screens import ScopeEditScreen

    class _H(App):
        def compose(self):
            return []

    app = _H()
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(ScopeEditScreen(engagement=Engagement.load("tests/data/sample.engagement.yaml")))
        for _ in range(4):
            await pilot.pause()
        scr = app.screen
        before = len(scr.query_one("#scope-entries", ListView).children)
        scr.query_one("#add-domains", Input).value = "*.new.example"
        await scr._add("domains")
        for _ in range(3):
            await pilot.pause()
        assert len(scr.query_one("#scope-entries", ListView).children) == before + 1
