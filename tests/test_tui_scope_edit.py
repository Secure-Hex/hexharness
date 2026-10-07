"""TUI: the full engagement editor edits every setting directly (no model), then persists + applies."""
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
from hexharness.tui.screens import EngagementEditScreen

EXAMPLE = "tests/data/sample.engagement.yaml"


def _temp_engagement() -> str:
    """A throwaway copy so persisting the edited engagement never clobbers the repo file."""
    dst = Path(tempfile.mkdtemp()) / "example.engagement.yaml"
    shutil.copy(EXAMPLE, dst)
    return str(dst)


async def test_edit_applies_and_persists_engagement():
    """Editing name + budget + a time window + report_template (plus scope) applies live."""
    app = HexTUI(engagement=_temp_engagement())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement(EXAMPLE, provider=None)
        base = Engagement.load(EXAMPLE).model_dump()

        async def edit(screen):
            return {
                **base,
                "name": "renamed-eng",
                "scope": {"domains": ["new.example"], "cidrs": [], "exclusions": []},
                "roe": {**base["roe"], "windows": [{"start": "08:00", "end": "20:00"}]},
                "budget": {"max_tokens": 123, "max_usd": 100.0, "max_seconds": None},
                "report_template": "custom.html.j2",
            }

        app.push_screen_wait = edit

        await app.action_edit_scope().wait()

        eng = app.engine.engagement
        assert eng.name == "renamed-eng"
        assert eng.budget.max_tokens == 123
        assert eng.budget.max_usd == 100.0
        assert eng.budget.max_seconds is None
        assert [(w.start, w.end) for w in eng.roe.windows] == [("08:00", "20:00")]
        assert eng.report_template == "custom.html.j2"
        guard = app.engine.control.scope_guard
        assert guard.in_scope("new.example") is True
        assert guard.in_scope("acme.example") is False  # old domain gone
        assert any(e.type is EventType.SCOPE_CHANGED for e in app.engine.events.all())
        # persisted copy survives a reload
        reloaded = Engagement.load(app.engagement_path)
        assert reloaded.name == "renamed-eng"
        assert reloaded.scope.domains == ["new.example"]
        assert reloaded.budget.max_tokens == 123


async def test_editor_renders_current_entries():
    eng = Engagement.load(EXAMPLE)
    app = HexTUI()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(EngagementEditScreen(engagement=eng))
        await pilot.pause()
        labels = [str(w.render()) for w in app.screen.query(Label)]
        assert any("acme.example" in t for t in labels)
        assert any("203.0.113.0/24" in t for t in labels)
        assert any("09:00" in t for t in labels)  # existing time window prefilled


async def test_invalid_input_not_applied():
    app = HexTUI(engagement=_temp_engagement())
    logs: list[str] = []
    app._log = lambda text, style=None: logs.append(text)  # type: ignore[assignment]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement(EXAMPLE, provider=None)
        before = list(app.engine.engagement.scope.cidrs)
        base = Engagement.load(EXAMPLE).model_dump()

        async def edit(screen):
            return {**base, "scope": {"domains": ["acme.example"], "cidrs": ["not-a-cidr"], "exclusions": []}}

        app.push_screen_wait = edit

        await app.action_edit_scope().wait()

        assert app.engine.engagement.scope.cidrs == before  # unchanged
        assert not any(e.type is EventType.SCOPE_CHANGED for e in app.engine.events.all())
        assert any("invalid engagement" in t.lower() for t in logs)


async def test_invalid_budget_number_not_applied():
    app = HexTUI(engagement=_temp_engagement())
    logs: list[str] = []
    app._log = lambda text, style=None: logs.append(text)  # type: ignore[assignment]
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement(EXAMPLE, provider=None)
        base = Engagement.load(EXAMPLE).model_dump()

        async def edit(screen):
            return {**base, "budget": {"max_tokens": "not-a-number", "max_usd": None, "max_seconds": None}}

        app.push_screen_wait = edit

        await app.action_edit_scope().wait()

        assert not any(e.type is EventType.SCOPE_CHANGED for e in app.engine.events.all())
        assert any("invalid engagement" in t.lower() for t in logs)


async def test_add_entry_no_duplicate_id_crash():
    """Regression: adding a scope entry used to crash with DuplicateIds because
    ListView.clear() is async and items were re-added with fixed ids before removal."""
    import pytest
    pytest.importorskip("textual")
    from textual.app import App
    from textual.widgets import Input, ListView
    from hexharness.engagement import Engagement
    from hexharness.tui.screens import EngagementEditScreen

    class _H(App):
        def compose(self):
            return []

    app = _H()
    async with app.run_test(size=(100, 30)) as pilot:
        app.push_screen(EngagementEditScreen(engagement=Engagement.load("tests/data/sample.engagement.yaml")))
        for _ in range(4):
            await pilot.pause()
        scr = app.screen
        before = len(scr.query_one("#scope-entries", ListView).children)
        scr.query_one("#add-domains", Input).value = "*.new.example"
        await scr._add("domains")
        for _ in range(3):
            await pilot.pause()
        assert len(scr.query_one("#scope-entries", ListView).children) == before + 1
