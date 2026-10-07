"""One call to go from an engagement's confirmed evidence to a rendered report file.

Orchestrates the three existing pieces: ReportModel.from_evidence (structural, reads
ONLY store.confirmed() — invariant #5), optional fill_generative (LLM prose), then
render (template -> html/pdf/docx/md). The default template ships in the package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from hexharness.evidence.store import EvidenceStore
from hexharness.reporting.model import ReportModel
from hexharness.reporting.render import render

DEFAULT_TEMPLATE = Path(__file__).parent / "templates" / "default.html.j2"


async def build_report(engagement_meta: Any, store: EvidenceStore, out_path: str | Path, *,
                       provider=None, template: str | Path | None = None,
                       model_name: str | None = None) -> Path:
    """Build + render a report. With a provider, also fills the LLM prose sections."""
    model = ReportModel.from_evidence(engagement_meta, store)
    if provider is not None:
        from hexharness.reporting.generate import fill_generative

        await fill_generative(model, provider, model_name=model_name)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return render(model, template or DEFAULT_TEMPLATE, out)
