"""The reporting glue added on top of the (already-tested) reporting module:
build_report() orchestration and the GenerateReportTool that writes into the workspace.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("jinja2")  # reporting render needs Jinja2 ([reporting] extra)

from hexharness.evidence.findings import Severity  # noqa: E402
from hexharness.evidence.store import EvidenceStore  # noqa: E402
from hexharness.reporting.build import build_report  # noqa: E402
from hexharness.tools.native.report_tools import GenerateReportTool  # noqa: E402


class _Eng:
    name = "demo"
    client = "ACME"

    class scope:  # noqa: N801
        cidrs: list[str] = []
        domains = ["app.test"]


async def _store_with_confirmed() -> EvidenceStore:
    store = EvidenceStore(":memory:")
    f = await store.add_candidate(title="SQLi in login", severity=Severity.HIGH,
                                  target="app.test", description="id param", cwe="CWE-89")
    await store.confirm(f.id, curator="op", reason="verified")
    # a candidate that is NOT confirmed must never reach the report (invariant #5)
    await store.add_candidate(title="noise", severity=Severity.LOW, target="app.test")
    return store


async def test_build_report_structural_only(tmp_path: Path) -> None:
    store = await _store_with_confirmed()
    out = await build_report(_Eng(), store, tmp_path / "r.html")  # no provider => structural
    txt = out.read_text()
    assert "SQLi in login" in txt and "ACME" in txt
    assert "noise" not in txt  # only confirmed findings


async def test_generate_report_tool_writes_to_workspace(tmp_path: Path) -> None:
    store = await _store_with_confirmed()
    tool = GenerateReportTool(store, _Eng(), tmp_path)
    out = await tool.run({"filename": "report.html", "generative": False})
    assert "report written to" in out and "1 confirmed finding" in out
    assert (tmp_path / "report.html").is_file()
