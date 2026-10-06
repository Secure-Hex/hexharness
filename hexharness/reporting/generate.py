"""Generative fill: executive_summary and risk_narrative, produced from the
already-structured ReportModel via an LLMProvider. No network beyond the provider;
no structural data is invented here — the model just prose-ifies the hard facts.
"""
from __future__ import annotations

from hexharness.providers.base import LLMProvider
from hexharness.providers.types import Message
from hexharness.reporting.model import ReportModel

_SYSTEM = (
    "You are a senior penetration tester writing the prose sections of a client "
    "report. Use only the facts provided. Be concise, factual, and professional. "
    "Return plain prose only — no markdown headings, no preamble."
)


def _facts(model: ReportModel) -> str:
    counts = ", ".join(f"{sev}: {n}" for sev, n in model.severity_counts.items() if n)
    lines = [
        f"Engagement: {model.engagement_name}",
        f"Client: {model.client}",
        f"Scope: {model.scope_summary}",
        f"Finding counts: {counts or 'none'}",
        "Findings:",
    ]
    lines += [f"  - [{f.severity}] {f.title} ({f.target or 'n/a'})" for f in model.findings]
    return "\n".join(lines)


async def fill_generative(model: ReportModel, provider: LLMProvider, *, model_name: str | None = None) -> ReportModel:
    """Populate model.executive_summary and model.risk_narrative in place."""
    facts = _facts(model)

    exec_resp = await provider.complete(
        [Message.user_text(
            f"{facts}\n\nWrite a 3-5 sentence executive summary for leadership."
        )],
        system=_SYSTEM,
        model=model_name,
    )
    risk_resp = await provider.complete(
        [Message.user_text(
            f"{facts}\n\nWrite a risk narrative (one paragraph) explaining the "
            f"business risk implied by these findings."
        )],
        system=_SYSTEM,
        model=model_name,
    )

    model.executive_summary = exec_resp.text().strip()
    model.risk_narrative = risk_resp.text().strip()
    return model
