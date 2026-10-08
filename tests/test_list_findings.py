"""list_findings: the read-back tool for the agent's own findings."""
from __future__ import annotations

from hexharness.evidence.findings import Severity
from hexharness.evidence.store import EvidenceStore
from hexharness.tools.native.evidence_tools import ListFindingsTool


async def test_list_findings_filters_and_sorts() -> None:
    store = EvidenceStore(":memory:")
    hi = await store.add_candidate(title="SQLi", severity=Severity.HIGH, target="app.test", cwe="CWE-89")
    await store.add_candidate(title="leak", severity=Severity.LOW, target="app.test")
    await store.confirm(hi.id, curator="op", reason="ok")
    tool = ListFindingsTool(store)

    all_out = await tool.run({})
    assert "2 finding(s)" in all_out
    # highest severity first
    assert all_out.index("SQLi") < all_out.index("leak")

    conf = await tool.run({"status": "confirmed", "detail": True})
    assert "SQLi" in conf and "leak" not in conf

    assert "No rejected findings" in await tool.run({"status": "rejected"})
    assert "unknown status" in await tool.run({"status": "bogus"})
