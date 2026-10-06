from __future__ import annotations

from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.recovery.snapshot import Recovery


async def test_rebuild_reconstructs_derived_state():
    store = EventStore(":memory:")
    await store.append(EventType.USER_PROMPT, {"text": "go"})
    await store.append(EventType.MODEL_RESPONSE, {"tokens": 120})
    await store.append(EventType.MODEL_RESPONSE, {"tokens": 80})
    await store.append(EventType.FINDING_CANDIDATE, {"id": "f1"})
    await store.append(EventType.FINDING_CANDIDATE, {"id": "f2"})
    await store.append(EventType.FINDING_CONFIRMED, {"id": "f1"})
    cp = await store.append(EventType.CHECKPOINT, {"reason": "test"})

    state = Recovery.rebuild(store.all())
    assert state.tokens_spent == 200
    assert set(state.findings_by_status["confirmed"]) == {"f1"}
    assert set(state.findings_by_status["candidate"]) == {"f2"}
    assert state.findings_by_status["rejected"] == []
    assert state.kill_requested is False
    assert state.last_checkpoint_seq == cp.seq
    # resume after the last checkpoint
    assert Recovery.resume_point(store.all()) == cp.seq


async def test_resume_point_without_checkpoint_is_last_seq():
    store = EventStore(":memory:")
    await store.append(EventType.USER_PROMPT, {"text": "go"})
    last = await store.append(EventType.MODEL_RESPONSE, {"tokens": 5})
    assert Recovery.resume_point(store.all()) == last.seq
    assert Recovery.resume_point([]) == 0


async def test_kill_requested_flag():
    store = EventStore(":memory:")
    await store.append(EventType.KILL_REQUESTED, {"who": "operator"})
    assert Recovery.rebuild(store.all()).kill_requested is True
