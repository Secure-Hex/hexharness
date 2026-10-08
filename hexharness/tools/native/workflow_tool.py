"""run_workflow — run a declarative multi-step tool pipeline.

Each step is executed through the SAME control-plane chokepoint as a normal tool call
(scope, ROE and HITL approval apply per step): Engine.loop() injects a step_runner that
routes every step through ControlPlane.authorize(). This tool only orchestrates order,
templating, for_each and conditions — it grants no new capability.
"""
from __future__ import annotations

from hexharness.agent.workflow import RunWorkflowInput, run_workflow
from hexharness.tools.base import RiskLevel, Tool


class RunWorkflowTool(Tool):
    name = "run_workflow"
    description = (
        "Run an ordered list of tool steps as one pipeline. Each step is {tool, input, "
        "output?, for_each?, condition?}. Strings in input use {{var}} templates; bind a "
        "step result with output and reuse it later. for_each iterates a {{var}} (per-item "
        "{{item}}); condition skips a step unless truthy ('{{x}} == text', '!=', 'contains'). "
        "Stops at the first failing step. EVERY step still passes scope/ROE/approval checks."
    )
    input_model = RunWorkflowInput
    # Orchestration only — real risk is enforced per step by the control plane.
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self) -> None:
        self.step_runner = None  # injected by Engine.loop(); authorizes+runs one step

    async def run(self, tool_input: dict) -> str:
        if self.step_runner is None:
            return "run_workflow is not wired to the control plane (no step runner)."
        data = RunWorkflowInput.model_validate(tool_input)
        return await run_workflow(data, self.step_runner)
