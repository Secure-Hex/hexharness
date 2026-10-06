from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    # Audit log, tracing and checkpointing are PROJECTIONS of this one stream.
    SESSION_STARTED = "session.started"
    USER_PROMPT = "agent.user_prompt"
    MODEL_RESPONSE = "agent.model_response"
    AUTHORIZE_DECISION = "control.authorize_decision"
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    FINDING_CANDIDATE = "evidence.finding_candidate"
    FINDING_CONFIRMED = "evidence.finding_confirmed"
    FINDING_REJECTED = "evidence.finding_rejected"
    BUDGET_UPDATED = "control.budget_updated"
    SECRET_PROVIDED = "control.secret_provided"  # name only — the value is never logged
    KILL_REQUESTED = "control.kill_requested"
    CHECKPOINT = "recovery.checkpoint"
    # Orchestrator-worker (phase 8): a subtask handed to / returned from a worker.
    DELEGATION_STARTED = "orchestrator.delegation_started"
    DELEGATION_FINISHED = "orchestrator.delegation_finished"


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


class Event(BaseModel):
    seq: int
    ts: str  # ISO-8601 UTC
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str = ""

    def compute_hash(self) -> str:
        material = f"{self.seq}|{self.ts}|{self.type.value}|{_canonical(self.payload)}|{self.prev_hash}"
        return hashlib.sha256(material.encode()).hexdigest()

    def sealed(self) -> "Event":
        return self.model_copy(update={"hash": self.compute_hash()})
