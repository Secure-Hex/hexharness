"""Session persistence: conversation round-trips, and events + findings survive a
reopen of the same engagement DB file."""
from __future__ import annotations

from hexharness import session as sess
from hexharness.engine import Engine
from hexharness.evidence.findings import Severity
from hexharness.evidence.store import EvidenceStore
from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.providers.types import Message, TextBlock, ToolUseBlock


def test_conversation_roundtrip(tmp_path):
    msgs = [
        Message.user_text("enumerate the perimeter"),
        Message(role=Message.user_text("x").role.ASSISTANT, content=[
            TextBlock(text="running recon"), ToolUseBlock(id="t1", name="dns_lookup", input={"host": "a.example"})]),
    ]
    sess.save_conversation("acme", msgs, root=tmp_path)
    assert sess.exists("acme", root=tmp_path) is False  # only conversation written, no db yet
    loaded = sess.load_conversation("acme", root=tmp_path)
    assert len(loaded) == 2
    assert loaded[1].content[1].name == "dns_lookup"


async def test_events_and_findings_persist_across_reopen(tmp_path):
    db = str(tmp_path / "session.sqlite")
    # first session: record an event + a finding
    events = EventStore(db)
    await events.append(EventType.USER_PROMPT, {"text": "hi"})
    evidence = EvidenceStore(db, events=events)
    f = await evidence.add_candidate(title="XSS", severity=Severity.HIGH)
    await evidence.confirm(f.id, curator="operator")
    events.close(); evidence.close()

    # reopen the SAME file: history + findings are still there
    events2 = EventStore(db)
    assert any(e.type is EventType.USER_PROMPT for e in events2.all())
    assert events2.verify() is True
    evidence2 = EvidenceStore(db)
    assert len(evidence2.confirmed()) == 1


def test_session_paths_use_engagement_slug(tmp_path):
    assert sess.db_path("ACME External", root=tmp_path).name == "session.sqlite"
    assert "acme-external" in str(sess.db_path("ACME External", root=tmp_path))
