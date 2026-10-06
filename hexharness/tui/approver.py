"""TUI human-in-the-loop approver: satisfies control.hitl.Approver."""
from __future__ import annotations

import asyncio

from textual.app import App

from hexharness.tui.screens import ApprovalModal


class TUIApprover:
    """Pushes an ApprovalModal and awaits the operator's decision via a Future.

    confirm() is called from the engine running on the app's event loop (inside the run
    worker), so push_screen and the Future resolve on the same loop — it works even while
    a run task is in flight.
    """

    def __init__(self, app: App) -> None:
        self._app = app

    async def confirm(self, *, tool: str, risk: str, target: str | None, reason: str) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        def _resolve(result: bool | None) -> None:
            if not future.done():
                future.set_result(bool(result))

        modal = ApprovalModal(tool=tool, risk=risk, target=target, reason=reason)
        self._app.push_screen(modal, _resolve)
        return await future
