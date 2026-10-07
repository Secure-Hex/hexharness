"""generate_report — render a client report from the engagement's CONFIRMED findings.

Reads only store.confirmed() (invariant #5), writes the file into the workspace (so it
persists on the host). The LLM prose sections are filled when a provider is available;
Engine.loop() injects the live provider onto the tool. PASSIVE: it only reads confirmed
evidence and writes a local file — no scanning, no network beyond the provider.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from hexharness.evidence.store import EvidenceStore
from hexharness.tools.base import RiskLevel, Tool


class GenerateReportInput(BaseModel):
    filename: str = Field(default="report.html",
                          description="Output filename in the workspace; extension picks the "
                                      "format (.html/.pdf/.docx/.md).")
    generative: bool = Field(default=True, description="Fill the LLM executive summary + risk narrative.")


class GenerateReportTool(Tool):
    name = "generate_report"
    description = ("Render a client report from the engagement's confirmed findings into the "
                   "workspace. Extension picks the format (.html/.pdf/.docx/.md).")
    input_model = GenerateReportInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, evidence: EvidenceStore, engagement, workspace: str | Path):
        self.evidence = evidence
        self.engagement = engagement  # for name/client/scope in the report header
        self.workspace = Path(workspace)
        self.provider = None  # set by Engine.loop() so generative fill can run

    async def run(self, tool_input: dict) -> str:
        from hexharness.reporting.build import build_report

        data = GenerateReportInput.model_validate(tool_input)
        out = self.workspace / data.filename
        provider = self.provider if data.generative else None
        try:
            path = await build_report(self.engagement, self.evidence, out, provider=provider)
        except Exception as exc:  # noqa: BLE001 — missing optional dep (weasyprint/docxtpl) etc.
            return f"report generation failed: {exc}"
        n = len(self.evidence.confirmed())
        return f"report written to {path} ({n} confirmed finding{'s' if n != 1 else ''})"
