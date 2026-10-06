"""Agent-facing tool exposing the skill library via progressive disclosure.

With no arguments the tool returns every skill's cheap metadata; with a name it
returns that one skill's full playbook body. This is the only path by which a
playbook's tokens enter the model's context.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field

from hexharness.skills.engine import SkillRegistry
from hexharness.tools.base import RiskLevel, Tool


class SkillLookupInput(BaseModel):
    skill_name: str | None = Field(
        default=None,
        description="Name of a skill to load its full playbook. Omit to list all "
        "available skills with their one-line summaries.",
    )


class SkillLookupTool(Tool):
    name = "skill_lookup"
    description = (
        "Browse the pentest skill library. Call with no arguments to list available "
        "skills (name, phase, description); call with skill_name to load that skill's "
        "full playbook."
    )
    input_model = SkillLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def run(self, tool_input: dict) -> str:
        name = tool_input.get("skill_name")
        if not name:
            listing = [
                {"name": m.name, "phase": m.phase, "description": m.description, "tags": m.tags}
                for m in self._registry.list_metadata()
            ]
            return json.dumps(listing, indent=2)
        try:
            return self._registry.load(name)
        except KeyError:
            available = ", ".join(m.name for m in self._registry.list_metadata())
            return f"unknown skill: {name}. Available: {available}"
