"""Kill switch — OUT OF BAND (invariant #6).

Not routed through the agent loop's channel: it fires from a POSIX signal (SIGUSR1) or
a watched trigger file, so it works even with the client disconnected. It checkpoints
BEFORE killing: the engine passes a checkpoint callback that snapshots state to the
event log, then the loop sees `triggered` at its next boundary and stops.
"""
from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

CheckpointFn = Callable[[], Awaitable[None] | None]


class KillSwitch:
    def __init__(self, *, trigger_file: str | Path | None = None, checkpoint: CheckpointFn | None = None):
        self._event = asyncio.Event()
        self._reason = ""
        self._trigger_file = Path(trigger_file) if trigger_file else None
        self._checkpoint = checkpoint
        self._watch_task: asyncio.Task | None = None

    @property
    def triggered(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    async def trigger(self, reason: str = "manual") -> None:
        if self._event.is_set():
            return
        self._reason = reason
        # Checkpoint BEFORE killing, so a resume has a clean point to replay to.
        if self._checkpoint:
            r = self._checkpoint()
            if asyncio.iscoroutine(r):
                await r
        self._event.set()

    def install_signal_handler(self, sig: int = signal.SIGUSR1) -> None:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(self.trigger(f"signal {sig}")))

    def start_file_watch(self, poll_seconds: float = 0.5) -> None:
        if not self._trigger_file:
            return

        async def _watch() -> None:
            while not self._event.is_set():
                if self._trigger_file.exists():
                    await self.trigger(f"trigger file {self._trigger_file}")
                    return
                await asyncio.sleep(poll_seconds)

        self._watch_task = asyncio.ensure_future(_watch())

    async def wait(self) -> None:
        await self._event.wait()
