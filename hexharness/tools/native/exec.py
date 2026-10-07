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
    network: str = Field(default="bridge", description="(informational) the session container is always on the bridge network")
    timeout: int = Field(default=60, description="Seconds before the container is killed")


class ExecCommandTool(Tool):
    name = "exec_command"
    description = ("Run a command inside the Docker sandbox (cwd /workspace, shared with "
                   "file_read/file_write and persisted on the host). Requires approval.")
    input_model = ExecCommandInput
    # INTRUSIVE, not DESTRUCTIVE: it runs in a throwaway container (can't harm the host).
    # Still requires approval — it is NOT scope-sensitive, so it can reach out over the network.
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "hexharness/kali:latest",
                 workspace: str | None = None):
        self.executor = executor or SandboxExecutor()
        self.image = image
        self.workspace = workspace  # mounted at /workspace; files persist on the host

    async def run(self, tool_input: dict) -> str:
        argv = tool_input["argv"]
        try:
            # One long-lived container per session: installs/state persist across calls
            # (only /workspace survives after the session closes).
            result = await self.executor.exec_in_session(
                self.image,
                argv,
                timeout=tool_input.get("timeout", 60),
                workspace=self.workspace,
            )
        except SandboxError as e:
            return f"sandbox unavailable: {e}"
        # ponytail: combine streams so the model sees whatever the command printed.
        combined = (result.stdout + result.stderr).strip()
        return combined if result.ok else f"exit {result.exit_code}\n{combined}"
