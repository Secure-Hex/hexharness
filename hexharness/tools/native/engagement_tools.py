"""engagement_draft — the agent turns a natural-language brief into a validated
engagement.yaml. It only DRAFTS to disk; the file is inert until a human activates it
(CLI `init` shows the full YAML and asks before anything runs under it). The model can
never grant itself scope or ROE at runtime — invariants #3/#4.
"""
from __future__ import annotations

from pathlib import Path

from hexharness.engagement_builder import EngagementSpec, render_yaml, write_engagement
from hexharness.tools.base import RiskLevel, Tool


class EngagementDraftTool(Tool):
    name = "engagement_draft"
    description = (
        "Draft a pentest engagement from a structured scope/ROE spec. Writes a validated "
        "engagement.yaml to disk and returns it for HUMAN review. Drafting does NOT activate "
        "it — a human must confirm before any session runs under it. Fill scope.domains/cidrs, "
        "scope.exclusions, roe.max_risk (passive|active|intrusive|destructive), roe.max_autonomy "
        "(plan|report|interactive|auto|bypass), roe.max_phase, and any time windows/budget."
    )
    input_model = EngagementSpec
    risk_level = RiskLevel.PASSIVE  # writes an inert draft file; nothing executes under it
    scope_sensitive = False
    requires_approval = False
    # ponytail: writes are confined to out_dir with a slugged filename; the real human
    # gate is activation, not drafting, so no HITL here.

    def __init__(self, out_dir: str | Path = "engagements", *, events=None):
        self.out_dir = Path(out_dir)
        self.events = events  # when set, emit ENGAGEMENT_PROPOSED so the TUI can offer activation

    async def run(self, tool_input: dict) -> str:
        spec = EngagementSpec.model_validate(tool_input)
        yaml_text = render_yaml(spec)  # raises on invalid scope/ROE before writing
        path = write_engagement(spec, self.out_dir)
        if self.events is not None:
            from hexharness.events.types import EventType

            # Propose only — activation is a human action in the TUI, never the model's.
            await self.events.append(EventType.ENGAGEMENT_PROPOSED, {"path": str(path), "name": spec.name})
        return (
            f"Proposed engagement written to {path} (NOT active — the operator must approve "
            f"it in the TUI before scope changes take effect).\n\n{yaml_text}"
        )
