"""Invariant #5: findings enter CANDIDATE; only CONFIRMED reach the report; REJECTED
is kept with a reason but the generator ignores it."""
from __future__ import annotations

from hexharness.events.store import EventStore
from hexharness.evidence.findings import FindingStatus, Severity
from hexharness.evidence.store import EvidenceStore


async def _store():
    events = EventStore(":memory:")
    return EvidenceStore(":memory:", events=events), events


async def test_enters_as_candidate():
    store, _ = await _store()
    f = await store.add_candidate(title="XSS", severity=Severity.HIGH, target="app.acme.example")
    assert f.status is FindingStatus.CANDIDATE
    assert store.confirmed() == []  # not in report yet


async def test_only_confirmed_reach_report():
    store, _ = await _store()
    a = await store.add_candidate(title="XSS", severity=Severity.HIGH)
    b = await store.add_candidate(title="noise", severity=Severity.INFO)
    await store.confirm(a.id, curator="matias", reason="reproduced")
    await store.reject(b.id, curator="matias", reason="false positive")

    confirmed = store.confirmed()
    assert [f.id for f in confirmed] == [a.id]
    assert confirmed[0].curator == "matias"
    # rejected is retained with its reason
    rej = store.rejected()
    assert len(rej) == 1 and rej[0].decision_reason == "false positive"


async def test_no_transition_from_terminal_state():
    store, _ = await _store()
    f = await store.add_candidate(title="X", severity=Severity.LOW)
    await store.confirm(f.id, curator="m")
    try:
        await store.reject(f.id, curator="m", reason="changed mind")
        assert False, "expected ValueError"
    except ValueError:
        pass


async def test_transitions_are_audited():
    store, events = await _store()
    f = await store.add_candidate(title="X", severity=Severity.LOW)
    await store.confirm(f.id, curator="m", reason="ok")
    types = [e.type.value for e in events.all()]
    assert "evidence.finding_candidate" in types
    assert "evidence.finding_confirmed" in types
