"""Session persistence: resume a HexHarness engagement later.

Everything for one engagement lives under .hexharness/<slug>/:
  - session.sqlite   : the event log (hash chain) AND the evidence/findings — both the
                       EventStore and EvidenceStore open this one file, so reopening it
                       restores the full audit trail and the findings in every state.
  - conversation.json: the agent conversation, so the model resumes with its context.

Budget spend is re-derived from the event log on resume (see recovery.Recovery).
"""
from __future__ import annotations

import json
from pathlib import Path

from hexharness.providers.types import Message


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())


def session_dir(engagement_name: str, *, root: str | Path = ".hexharness") -> Path:
    return Path(root) / _slug(engagement_name)


def db_path(engagement_name: str, *, root: str | Path = ".hexharness") -> Path:
    return session_dir(engagement_name, root=root) / "session.sqlite"


def conversation_path(engagement_name: str, *, root: str | Path = ".hexharness") -> Path:
    return session_dir(engagement_name, root=root) / "conversation.json"


def exists(engagement_name: str, *, root: str | Path = ".hexharness") -> bool:
    return db_path(engagement_name, root=root).exists()


def save_conversation(engagement_name: str, messages: list[Message], *,
                      root: str | Path = ".hexharness") -> None:
    path = conversation_path(engagement_name, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [m.model_dump(mode="json") for m in messages]
    path.write_text(json.dumps(data, indent=2))


def load_conversation(engagement_name: str, *, root: str | Path = ".hexharness") -> list[Message]:
    path = conversation_path(engagement_name, root=root)
    try:
        return [Message.model_validate(d) for d in json.loads(path.read_text())]
    except Exception:  # noqa: BLE001 — missing/corrupt => empty history
        return []
