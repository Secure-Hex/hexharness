"""Append-only event log with a SHA-256 hash chain, backed by SQLite.

Single source of truth for the engine. Audit log, OTel traces and checkpoints are
all PROJECTIONS of this stream, not separate systems. Designed to migrate to Postgres
(the SQL is plain; only the connection factory would change).
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexharness.events.bus import EventBus
from hexharness.events.types import Event, EventType

GENESIS_HASH = "0" * 64


class HashChainError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventStore:
    def __init__(self, path: str | Path = ":memory:", *, bus: EventBus | None = None):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL UNIQUE
            )"""
        )
        self._conn.commit()
        self._bus = bus
        self._lock = asyncio.Lock()  # serialize appends so the chain stays linear

    def _last(self) -> tuple[int, str]:
        row = self._conn.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return (row[0], row[1]) if row else (0, GENESIS_HASH)

    async def append(self, type: EventType, payload: dict[str, Any] | None = None) -> Event:
        async with self._lock:
            last_seq, prev_hash = self._last()
            event = Event(
                seq=last_seq + 1, ts=_now(), type=type, payload=payload or {}, prev_hash=prev_hash
            ).sealed()
            self._conn.execute(
                "INSERT INTO events (seq, ts, type, payload, prev_hash, hash) VALUES (?,?,?,?,?,?)",
                (event.seq, event.ts, event.type.value, json.dumps(event.payload, default=str),
                 event.prev_hash, event.hash),
            )
            self._conn.commit()
        if self._bus:
            await self._bus.publish(event)
        return event

    def all(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT seq, ts, type, payload, prev_hash, hash FROM events ORDER BY seq"
        ).fetchall()
        return [
            Event(seq=r[0], ts=r[1], type=EventType(r[2]), payload=json.loads(r[3]),
                  prev_hash=r[4], hash=r[5])
            for r in rows
        ]

    def verify(self) -> bool:
        """Walk the chain; raise HashChainError on any break or tamper."""
        prev = GENESIS_HASH
        expected_seq = 1
        for e in self.all():
            if e.seq != expected_seq:
                raise HashChainError(f"seq gap at {e.seq}, expected {expected_seq}")
            if e.prev_hash != prev:
                raise HashChainError(f"prev_hash break at seq {e.seq}")
            if e.hash != e.compute_hash():
                raise HashChainError(f"tampered payload at seq {e.seq}")
            prev = e.hash
            expected_seq += 1
        return True

    def close(self) -> None:
        self._conn.close()
