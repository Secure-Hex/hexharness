from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(str, Enum):
    # Invariant #5: everything enters CANDIDATE. Only CONFIRMED reaches the report.
    # REJECTED is kept (with a reason, in the audit log) but the generator ignores it.
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Finding(BaseModel):
    id: str
    title: str
    severity: Severity
    status: FindingStatus = FindingStatus.CANDIDATE
    target: str | None = None
    description: str = ""
    reproduction: str = ""  # PoC / step-by-step to reproduce and verify (real vs false positive)
    evidence: list[str] = Field(default_factory=list)  # refs: event seqs, file paths, output hashes
    cwe: str | None = None
    # Curation trail (human-in-the-loop). Set on confirm/reject.
    curator: str | None = None
    decision_reason: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
