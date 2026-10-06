"""Findings curation panel. Skipped if Textual isn't installed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from hexharness.evidence.findings import Severity  # noqa: E402
from hexharness.evidence.store import EvidenceStore  # noqa: E402
from hexharness.tui.app import HexTUI  # noqa: E402
from hexharness.tui.screens import FindingsScreen  # noqa: E402


async def _store_with_candidates() -> EvidenceStore:
    store = EvidenceStore(":memory:")  # real in-memory store, no events bus
    await store.add_candidate(title="SQLi in /login", severity=Severity.HIGH, target="/login")
    await store.add_candidate(title="Missing CSP header", severity=Severity.LOW, target="/")
    return store


async def test_grouping_counts_and_confirm_moves_out_of_candidates():
    store = await _store_with_candidates()
    fake = SimpleNamespace(evidence=store)
    screen = FindingsScreen(engine=fake)

    cands, conf, rej = screen._groups()
    assert len(cands) == 2 and len(conf) == 0 and len(rej) == 0
    assert "2 candidate · 0 confirmed · 0 rejected" in screen._title()

    # Drive a confirm through the screen; it re-reads the store afterward.
    await screen.confirm_finding(cands[0].id)
    cands2, conf2, rej2 = screen._groups()
    assert len(cands2) == 1 and len(conf2) == 1 and len(rej2) == 0
    assert cands[0].id not in {f.id for f in cands2}
    assert conf2[0].id == cands[0].id


async def test_ctrl_f_without_engine_shows_empty_state(monkeypatch):
    # No provider key -> engine can't build -> action_findings swallows RuntimeError and
    # the screen shows its empty-state note. Force the failure so it's env-independent.
    def _no_key(self):
        raise RuntimeError("no API key configured")

    monkeypatch.setattr(HexTUI, "_make_provider", _no_key)
    app = HexTUI()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, FindingsScreen)
        text = "\n".join(str(w.render()) for w in app.screen.query(Static))
        assert "no engagement running yet" in text
