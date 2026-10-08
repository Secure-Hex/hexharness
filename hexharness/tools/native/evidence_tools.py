"""record_finding — the agent logs a security finding into the Evidence Store.

It always enters as a CANDIDATE (invariant #5): only human curation (confirm) promotes
it to the report; the model can never write a confirmed finding. PASSIVE and not
scope-sensitive — it's local bookkeeping, not an action against a target.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.evidence.findings import Severity
from hexharness.tools.base import RiskLevel, Tool

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


class RecordFindingInput(BaseModel):
    title: str = Field(description="Short finding title")
    severity: str = Field(default="medium", description="info | low | medium | high | critical")
    target: str | None = Field(default=None, description="Affected host/URL, if any")
    description: str = ""
    reproduction: str = Field(default="", description="PoC / step-by-step to reproduce and verify")
    cwe: str | None = Field(default=None, description="e.g. CWE-79")
    evidence: list[str] = Field(default_factory=list, description="refs: event seqs, paths, hashes")


class RecordFindingTool(Tool):
    name = "record_finding"
    description = (
        "Record a security finding as a CANDIDATE in the evidence store. It only reaches "
        "the report after a human confirms it. Provide title, severity, target, a clear "
        "description, a reproduction (PoC / step-by-step so a human can verify it is real), "
        "evidence refs, and the CWE."
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
            description=data.description, reproduction=data.reproduction,
            evidence=data.evidence, cwe=data.cwe,
        )
        return (f"Recorded CANDIDATE finding {f.id}: {f.title} [{severity.value}]. "
                "Awaiting human curation before it can reach the report.")


class ListFindingsInput(BaseModel):
    status: str = Field(default="all",
                        description="Filter: all | candidate | confirmed | rejected")
    detail: bool = Field(default=False,
                         description="Include description, reproduction and evidence per finding")


class ListFindingsTool(Tool):
    name = "list_findings"
    description = (
        "List the findings already recorded this engagement, with their status "
        "(candidate/confirmed/rejected), severity and target. Use it to see what you have "
        "before recording duplicates or generating a report. Set detail=true for the full "
        "description, reproduction and evidence of each."
    )
    input_model = ListFindingsInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, evidence_store):
        self.evidence = evidence_store

    async def run(self, tool_input: dict) -> str:
        data = ListFindingsInput.model_validate(tool_input)
        status = data.status.lower()
        buckets = {"candidate": self.evidence.candidates, "confirmed": self.evidence.confirmed,
                   "rejected": self.evidence.rejected}
        if status in buckets:
            findings = buckets[status]()
        elif status == "all":
            findings = [f for get in buckets.values() for f in get()]
        else:
            return f"unknown status '{data.status}' — use all|candidate|confirmed|rejected"
        if not findings:
            return f"No {status if status != 'all' else ''} findings recorded yet.".replace("  ", " ")
        findings.sort(key=lambda f: (_SEVERITY_RANK.get(f.severity.value, 9), f.status.value))
        lines = [f"{len(findings)} finding(s):"]
        for f in findings:
            tgt = f" @ {f.target}" if f.target else ""
            cwe = f" {f.cwe}" if f.cwe else ""
            lines.append(f"  [{f.status.value}] {f.id} — {f.title} ({f.severity.value}{cwe}){tgt}")
            if data.detail:
                if f.description:
                    lines.append(f"      desc: {f.description}")
                if f.reproduction:
                    lines.append(f"      repro: {f.reproduction}")
                if f.evidence:
                    lines.append(f"      evidence: {', '.join(f.evidence)}")
        return "\n".join(lines)
