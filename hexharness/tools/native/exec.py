"""Command execution, always inside the Docker sandbox — never on the host.

argv is forwarded to the sandbox as a list, so tool inputs can never be assembled into
a shell string and injected. DESTRUCTIVE + requires_approval: arbitrary code execution.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxError, SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool


class ExecCommandInput(BaseModel):
    argv: list[str] = Field(description="Command and args as a list (no shell), e.g. ['id']")
    network: str = Field(default="none", description="Docker network mode ('none' or 'bridge')")
    timeout: int = Field(default=60, description="Seconds before the container is killed")


class ExecCommandTool(Tool):
    name = "exec_command"
    description = "Run a command inside the Docker sandbox. Destructive — requires approval."
    input_model = ExecCommandInput
    risk_level = RiskLevel.DESTRUCTIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "alpine:3.20"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        argv = tool_input["argv"]
        try:
            result = await self.executor.run(
                self.image,
                argv,
                network=tool_input.get("network", "none"),
                timeout=tool_input.get("timeout", 60),
            )
        except SandboxError as e:
            return f"sandbox unavailable: {e}"
        # ponytail: combine streams so the model sees whatever the command printed.
        combined = (result.stdout + result.stderr).strip()
        return combined if result.ok else f"exit {result.exit_code}\n{combined}"
