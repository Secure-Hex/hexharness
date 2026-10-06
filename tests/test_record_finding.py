"""record_finding logs a CANDIDATE (never confirmed) — invariant #5."""
from __future__ import annotations

from hexharness.evidence.findings import FindingStatus, Severity
from hexharness.evidence.store import EvidenceStore
from hexharness.tools.native.evidence_tools import RecordFindingTool


async def test_records_candidate_only():
    store = EvidenceStore(":memory:")
    tool = RecordFindingTool(store)
    out = await tool.run({"title": "Reflected XSS", "severity": "high",
                          "target": "app.acme.example", "cwe": "CWE-79"})
    assert "CANDIDATE" in out
    cands = store.candidates()
    assert len(cands) == 1
    assert cands[0].status is FindingStatus.CANDIDATE
    assert cands[0].severity is Severity.HIGH
    assert store.confirmed() == []  # never auto-confirmed


async def test_bad_severity_defaults_to_medium():
    store = EvidenceStore(":memory:")
    await RecordFindingTool(store).run({"title": "x", "severity": "catastrophic"})
    assert store.candidates()[0].severity is Severity.MEDIUM


def test_registered_when_evidence_present():
    from hexharness.engine import default_registry

    store = EvidenceStore(":memory:")
    names = [s.name for s in default_registry(evidence=store).specs()]
    assert "record_finding" in names
