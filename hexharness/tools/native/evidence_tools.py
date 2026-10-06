"""record_finding — the agent logs a security finding into the Evidence Store.

It always enters as a CANDIDATE (invariant #5): only human curation (confirm) promotes
it to the report; the model can never write a confirmed finding. PASSIVE and not
scope-sensitive — it's local bookkeeping, not an action against a target.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.evidence.findings import Severity
from hexharness.tools.base import RiskLevel, Tool


class RecordFindingInput(BaseModel):
    title: str = Field(description="Short finding title")
    severity: str = Field(default="medium", description="info | low | medium | high | critical")
    target: str | None = Field(default=None, description="Affected host/URL, if any")
    description: str = ""
    cwe: str | None = Field(default=None, description="e.g. CWE-79")
    evidence: list[str] = Field(default_factory=list, description="refs: event seqs, paths, hashes")


class RecordFindingTool(Tool):
    name = "record_finding"
    description = (
        "Record a security finding as a CANDIDATE in the evidence store. It only reaches "
        "the report after a human confirms it. Provide title, severity, and ideally target, "
        "description, and CWE."
    )
    input_model = RecordFindingInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, evidence_store):
        self.evidence = evidence_store

    async def run(self, tool_input: dict) -> str:
        data = RecordFindingInput.model_validate(tool_input)
        try:
            severity = Severity(data.severity.lower())
        except ValueError:
            severity = Severity.MEDIUM
        f = await self.evidence.add_candidate(
            title=data.title, severity=severity, target=data.target,
            description=data.description, evidence=data.evidence, cwe=data.cwe,
        )
        return (f"Recorded CANDIDATE finding {f.id}: {f.title} [{severity.value}]. "
                "Awaiting human curation before it can reach the report.")
