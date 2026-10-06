"""Evidence Store. Findings move candidate -> confirmed/rejected only through here,
and every transition emits an event (audit trail). The report generator calls
`confirmed()` and never sees candidates or rejections — invariant #5.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.evidence.findings import Finding, FindingStatus, Severity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceStore:
    def __init__(self, path: str | Path = ":memory:", *, events: EventStore | None = None):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                status TEXT NOT NULL
            )"""
        )
        self._conn.commit()
        self._events = events

    def _save(self, f: Finding) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO findings (id, data, status) VALUES (?,?,?)",
            (f.id, f.model_dump_json(), f.status.value),
        )
        self._conn.commit()

    async def add_candidate(
        self, *, title: str, severity: Severity, target: str | None = None,
        description: str = "", evidence: list[str] | None = None, cwe: str | None = None,
    ) -> Finding:
        f = Finding(
            id=uuid.uuid4().hex, title=title, severity=severity, target=target,
            description=description, evidence=evidence or [], cwe=cwe,
        )
        self._save(f)
        if self._events:
            await self._events.append(EventType.FINDING_CANDIDATE, {"id": f.id, "title": title, "severity": severity.value})
        return f

    def get(self, finding_id: str) -> Finding | None:
        row = self._conn.execute("SELECT data FROM findings WHERE id=?", (finding_id,)).fetchone()
        return Finding.model_validate_json(row[0]) if row else None

    async def _transition(self, finding_id: str, status: FindingStatus, curator: str, reason: str, event: EventType) -> Finding:
        f = self.get(finding_id)
        if f is None:
            raise KeyError(finding_id)
        if f.status is not FindingStatus.CANDIDATE:
            raise ValueError(f"{finding_id} already {f.status.value}; transitions are from CANDIDATE only")
        f = f.model_copy(update={"status": status, "curator": curator, "decision_reason": reason, "updated_at": _now()})
        self._save(f)
        if self._events:
            await self._events.append(event, {"id": f.id, "curator": curator, "reason": reason})
        return f

    async def confirm(self, finding_id: str, *, curator: str, reason: str = "") -> Finding:
        return await self._transition(finding_id, FindingStatus.CONFIRMED, curator, reason, EventType.FINDING_CONFIRMED)

    async def reject(self, finding_id: str, *, curator: str, reason: str) -> Finding:
        return await self._transition(finding_id, FindingStatus.REJECTED, curator, reason, EventType.FINDING_REJECTED)

    def _by_status(self, status: FindingStatus) -> list[Finding]:
        rows = self._conn.execute("SELECT data FROM findings WHERE status=?", (status.value,)).fetchall()
        return [Finding.model_validate_json(r[0]) for r in rows]

    def confirmed(self) -> list[Finding]:
        """The ONLY findings the report generator is allowed to see."""
        return self._by_status(FindingStatus.CONFIRMED)

    def candidates(self) -> list[Finding]:
        return self._by_status(FindingStatus.CANDIDATE)

    def rejected(self) -> list[Finding]:
        return self._by_status(FindingStatus.REJECTED)

    def close(self) -> None:
        self._conn.close()
