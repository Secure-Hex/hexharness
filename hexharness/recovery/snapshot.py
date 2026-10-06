"""Recovery projection: replay the event stream to reconstruct derived state.

The checkpointing view of the one append-only stream. Nothing here is a separate
store; `rebuild` is a pure fold over events, so resume-after-crash is just
"replay the log and continue after the last checkpoint".
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.events.types import Event, EventType

_STATUS = {
    EventType.FINDING_CANDIDATE: "candidate",
    EventType.FINDING_CONFIRMED: "confirmed",
    EventType.FINDING_REJECTED: "rejected",
}


class RecoveredState(BaseModel):
    tokens_spent: int = 0
    findings_by_status: dict[str, list[str]] = Field(
        default_factory=lambda: {"candidate": [], "confirmed": [], "rejected": []}
    )
    last_checkpoint_seq: int | None = None
    kill_requested: bool = False
    last_seq: int = 0


class Recovery:
    @staticmethod
    def rebuild(events: list[Event]) -> RecoveredState:
        state = RecoveredState()
        # id -> current status; a finding moves candidate -> confirmed/rejected.
        status_of: dict[str, str] = {}
        for e in events:
            state.last_seq = e.seq
            if e.type is EventType.MODEL_RESPONSE:
                state.tokens_spent += int(e.payload.get("tokens", 0))
            elif e.type in _STATUS:
                fid = e.payload.get("id")
                if fid is not None:
                    status_of[fid] = _STATUS[e.type]
            elif e.type is EventType.CHECKPOINT:
                state.last_checkpoint_seq = e.seq
            elif e.type is EventType.KILL_REQUESTED:
                state.kill_requested = True

        for status in state.findings_by_status:
            state.findings_by_status[status] = [i for i, s in status_of.items() if s == status]
        return state

    @staticmethod
    def resume_point(events: list[Event]) -> int:
        """Seq to resume AFTER: last CHECKPOINT if any, else the last seq (0 if empty)."""
        for e in reversed(events):
            if e.type is EventType.CHECKPOINT:
                return e.seq
        return events[-1].seq if events else 0
