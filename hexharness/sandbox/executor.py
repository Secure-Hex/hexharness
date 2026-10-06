"""Docker-backed sandbox. Shells out to the docker CLI (no SDK dependency).

Tools run in a throwaway container, hardened by default (no new privileges, all caps
dropped, pid/memory limits). argv is passed as a list — never a shell string — so tool
inputs cannot inject a command. Network is opt-in per call because a scanner needs it
but a parser does not.
"""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass


class SandboxError(RuntimeError):
    pass


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class SandboxExecutor:
    def __init__(self, *, docker_bin: str = "docker", default_timeout: float = 120.0):
        self.docker_bin = docker_bin
        self.default_timeout = default_timeout

    def available(self) -> bool:
        return shutil.which(self.docker_bin) is not None

    async def run(
        self,
        image: str,
        argv: list[str],
        *,
        network: str = "none",
        timeout: float | None = None,
        memory: str = "512m",
        pids_limit: int = 256,
    ) -> SandboxResult:
        if not self.available():
            raise SandboxError("docker not found on PATH")

        cmd = [
            self.docker_bin, "run", "--rm",
            "--network", network,
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--memory", memory,
            "--pids-limit", str(pids_limit),
            image, *argv,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout or self.default_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise SandboxError(f"sandbox timeout after {timeout or self.default_timeout}s")
        return SandboxResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))
