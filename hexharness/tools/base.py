from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum

from pydantic import BaseModel

from hexharness.providers.types import ToolSpec


class RiskLevel(IntEnum):
    """Ordered so comparisons (>, min) mean "more dangerous". The control plane and
    ROE/phase ceilings rely on this ordering."""

    PASSIVE = 0       # read-only, no packets at target (lookups, local parsing)
    ACTIVE = 1        # touches target benignly (dns, banner grab, light enum)
    INTRUSIVE = 2     # exploit attempts, auth brute, injection
    DESTRUCTIVE = 3   # data modification/deletion, DoS-capable


class Tool(ABC):
    """A tool declares its own risk posture. These three fields are what the control
    plane reads — the model never sees them."""

    name: str
    description: str
    input_model: type[BaseModel]
    risk_level: RiskLevel
    scope_sensitive: bool
    requires_approval: bool = False
    # Name of the input field that holds the scope target (host/ip/url). Required
    # when scope_sensitive is True so the Scope Guard knows what to check.
    target_field: str | None = None
    # Secrets this tool needs present in the Vault before it may run. If one is missing,
    # the control plane asks the operator out-of-band (never the model) and stores it.
    required_secrets: list[str] = []

    def to_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_model.model_json_schema(),
        )

    def extract_target(self, tool_input: dict) -> str | None:
        if not self.scope_sensitive or not self.target_field:
            return None
        return tool_input.get(self.target_field)

    @abstractmethod
    async def run(self, tool_input: dict) -> str:
        """Execute. MUST NOT be called directly by the agent loop — only the executor,
        and only after ControlPlane.authorize() returned ALLOW (invariant #1)."""
        raise NotImplementedError
