"""Canonical report schema. Templates are written AGAINST this model, and the
placeholder validator (render.py) checks every template against these field names.

Two kinds of fill:
  * STRUCTURAL  -> ReportModel.from_evidence(): hard data straight from the
    EvidenceStore, no LLM. INVARIANT #5: only store.confirmed() is ever read.
  * GENERATIVE  -> generate.fill_generative(): executive_summary / risk_narrative,
    produced by an LLMProvider from the structural data.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Any, Mapping

from pydantic import BaseModel, Field

from hexharness.evidence.findings import Finding, Severity
from hexharness.evidence.store import EvidenceStore

# Highest first — drives finding ordering and the severity_counts layout.
_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


class ReportFinding(BaseModel):
    """The report's view of a Finding. Deliberately decoupled from the curation
    fields (status/curator/decision_reason) — a report only shows confirmed facts."""

    id: str
    title: str
    severity: str  # ponytail: plain string so templates write {{ f.severity }}, not {{ f.severity.value }}
    target: str | None = None
    description: str = ""
    cwe: str | None = None
    evidence: list[str] = Field(default_factory=list)

    @classmethod
    def from_finding(cls, f: Finding) -> "ReportFinding":
        return cls(
            id=f.id,
            title=f.title,
            severity=f.severity.value,
            target=f.target,
            description=f.description,
            cwe=f.cwe,
            evidence=list(f.evidence),
        )


class ReportModel(BaseModel):
    engagement_name: str
    client: str = ""
    date: str = Field(default_factory=lambda: _date.today().isoformat())
    scope_summary: str = ""
    findings: list[ReportFinding] = Field(default_factory=list)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    # Generative fields — empty until fill_generative() runs.
    executive_summary: str = ""
    risk_narrative: str = ""

    @classmethod
    def from_evidence(cls, engagement_meta: Mapping[str, Any] | Any, store: EvidenceStore) -> "ReportModel":
        """Structural fill only. Reads ONLY store.confirmed() — invariant #5."""
        confirmed = store.confirmed()
        confirmed.sort(key=lambda f: _SEVERITY_ORDER.index(f.severity))

        counts = {s.value: 0 for s in _SEVERITY_ORDER}
        for f in confirmed:
            counts[f.severity.value] += 1

        return cls(
            engagement_name=_meta(engagement_meta, "name", default="engagement") or "engagement",
            client=_meta(engagement_meta, "client", default=""),
            date=_meta(engagement_meta, "date", default=_date.today().isoformat()),
            scope_summary=_scope_summary(engagement_meta),
            findings=[ReportFinding.from_finding(f) for f in confirmed],
            severity_counts=counts,
        )


def _meta(meta: Mapping[str, Any] | Any, key: str, *, default: Any = "") -> Any:
    """engagement_meta may be a dict or an object (e.g. an Engagement)."""
    if isinstance(meta, Mapping):
        return meta.get(key, default)
    return getattr(meta, key, default)


def _scope_summary(meta: Mapping[str, Any] | Any) -> str:
    explicit = _meta(meta, "scope_summary", default=None)
    if explicit:
        return explicit
    scope = _meta(meta, "scope", default=None)  # Engagement.scope -> cidrs/domains
    if scope is None:
        return ""
    targets = list(_meta(scope, "cidrs", default=[])) + list(_meta(scope, "domains", default=[]))
    return ", ".join(targets)
