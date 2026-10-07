"""TUI: a proposed scope change applies only after operator approval; reject leaves it."""
from __future__ import annotations

import tempfile

import pytest

pytest.importorskip("textual")

from hexharness.engagement_builder import EngagementSpec, write_engagement
from hexharness.engine import Engine
from hexharness.tui.app import HexTUI


def _proposed(name="pivot", domain="other.example"):
    return str(write_engagement(
        EngagementSpec.model_validate({"name": name, "scope": {"domains": [domain]},
                                       "roe": {"max_risk": "passive"}}),
        tempfile.mkdtemp(),
    ))


async def test_approval_applies_scope():
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement("tests/data/sample.engagement.yaml", provider=None)

        async def approve(screen):
            return True
        app.push_screen_wait = approve

        app._propose_scope(_proposed())
        await pilot.pause()
        await pilot.pause()
        assert app.engine.engagement.name == "pivot"
        assert app.engine.control.scope_guard.in_scope("other.example") is True


async def test_rejection_keeps_scope():
    app = HexTUI()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.engine = Engine.from_engagement("tests/data/sample.engagement.yaml", provider=None)

        async def reject(screen):
            return False
        app.push_screen_wait = reject

        app._propose_scope(_proposed())
        await pilot.pause()
        await pilot.pause()
        assert app.engine.engagement.name == "acme-external-2026"  # unchanged
