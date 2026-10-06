from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class _In(BaseModel):
    host: str = Field(default="host.example")


class SpyTool(Tool):
    """Records whether run() was ever called. Used to prove the chokepoint blocks
    execution — if run() fires on a denied call, the invariant is broken."""

    input_model = _In

    def __init__(self, name: str, risk: RiskLevel, *, scope_sensitive=False,
                 requires_approval=False, target_field=None):
        self.name = name
        self.description = f"spy {name}"
        self.risk_level = risk
        self.scope_sensitive = scope_sensitive
        self.requires_approval = requires_approval
        self.target_field = target_field
        self.ran = False
        self.ran_with: dict | None = None

    async def run(self, tool_input: dict) -> str:
        self.ran = True
        self.ran_with = tool_input
        return f"{self.name} executed"
