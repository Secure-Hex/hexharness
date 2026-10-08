"""A provider timeout/error during manual compaction must never crash the TUI —
it logs and leaves the transcript untouched."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from hexharness.tui.app import HexTUI


class _RaisingLoop:
    """Minimal stand-in whose compact() fails like a provider timeout."""
    last_input_tokens = 0

    def __init__(self, exc: Exception):
        self._exc = exc

    async def compact(self, *, reason: str) -> int:
        raise self._exc


@pytest.mark.parametrize("exc", [TimeoutError(), RuntimeError("boom")])
async def test_compact_failure_does_not_crash(exc):
    app = HexTUI()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app.loop = _RaisingLoop(exc)
        app._compact()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.is_running  # worker swallowed the error; UI stayed up
