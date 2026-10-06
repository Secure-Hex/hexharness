"""Event backbone: append-only log with a tamper-evident hash chain."""
from __future__ import annotations

import json

from hexharness.events.store import EventStore, HashChainError
from hexharness.events.types import EventType


async def test_chain_verifies_after_appends():
    store = EventStore(":memory:")
    for i in range(5):
        await store.append(EventType.CHECKPOINT, {"i": i})
    assert store.verify() is True
    events = store.all()
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].prev_hash == "0" * 64
    for a, b in zip(events, events[1:]):
        assert b.prev_hash == a.hash


async def test_tamper_detected():
    store = EventStore(":memory:")
    await store.append(EventType.CHECKPOINT, {"i": 0})
    await store.append(EventType.CHECKPOINT, {"i": 1})
    # Tamper directly in the DB, leaving the stored hash intact.
    store._conn.execute("UPDATE events SET payload=? WHERE seq=1", (json.dumps({"i": 999}),))
    store._conn.commit()
    try:
        store.verify()
        assert False, "expected HashChainError"
    except HashChainError:
        pass
