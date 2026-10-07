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
from pathlib import Path


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
        cap_add: list[str] | None = None,
        workspace: str | Path | None = None,
    ) -> SandboxResult:
        if not self.available():
            raise SandboxError("docker not found on PATH")

        # Mount the engagement workspace read-write at /workspace (and cd there) so files
        # the command creates persist on the host and are shared with file_read/file_write.
        mount: list[str] = []
        if workspace is not None:
            ws = Path(workspace).resolve()
            ws.mkdir(parents=True, exist_ok=True)
            # World-writable so the container can write regardless of uid remapping
            # (rootless/userns Docker maps container-root to an unprivileged host uid).
            # ponytail: it's a per-engagement scratch dir; 0777 is acceptable here.
            try:
                ws.chmod(0o777)
            except OSError:
                pass
            mount = ["-v", f"{ws}:/workspace", "-w", "/workspace"]

        # Drop all caps, then add back only the ones the tool explicitly needs (e.g.
        # NET_RAW for nmap SYN/OS scans). no-new-privileges is dropped when caps are
        # granted, since it would block them from taking effect.
        caps: list[str] = []
        for c in cap_add or []:
            caps += ["--cap-add", c]
        security = [] if cap_add else ["--security-opt", "no-new-privileges"]
        cmd = [
            self.docker_bin, "run", "--rm",
            "--network", network,
            *security,
            "--cap-drop", "ALL", *caps,
            *mount,
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
