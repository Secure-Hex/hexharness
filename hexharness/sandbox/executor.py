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
        self._session_container: str | None = None  # long-lived container for exec_command

    def available(self) -> bool:
        return shutil.which(self.docker_bin) is not None

    # -- session container (exec_command) -------------------------------------------------
    # One long-lived container per HexHarness session: each exec_command execs into it, so
    # installs/state persist for the whole session. Only /workspace (host-mounted) survives
    # after close_session() removes it. Scanners keep using ephemeral run() — they install
    # nothing and want per-call caps (e.g. NET_RAW).

    def _session_name(self, workspace: str | Path | None) -> str:
        base = Path(workspace).parent.name if workspace else "default"
        return f"hexharness-{base}"

    async def _ensure_session(self, image: str, workspace: str | Path | None) -> str:
        if not self.available():
            raise SandboxError("docker not found on PATH")
        if self._session_container is not None:
            return self._session_container

        from hexharness.sandbox.image import build_image, image_exists, is_hexharness_image

        if is_hexharness_image(image) and not image_exists(image, docker_bin=self.docker_bin):
            ok, out = await build_image(image, docker_bin=self.docker_bin)
            if not ok:
                raise SandboxError(f"failed to build sandbox image {image}:\n{out}")

        name = self._session_name(workspace)
        # Crash recovery: drop any stale container left by a hard-killed previous session.
        stale = await asyncio.create_subprocess_exec(
            self.docker_bin, "rm", "-f", name,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await stale.wait()

        mount: list[str] = []
        if workspace is not None:
            ws = Path(workspace).resolve()
            ws.mkdir(parents=True, exist_ok=True)
            try:
                ws.chmod(0o777)  # rootless/userns: container uid may differ from host uid
            except OSError:
                pass
            mount = ["-v", f"{ws}:/workspace", "-w", "/workspace"]
        # Default caps + bridge so apt-get/dpkg and any command work; `sleep infinity`
        # keeps it alive so we can exec into it until close_session().
        cmd = [self.docker_bin, "run", "-d", "--name", name, "--network", "bridge",
               *mount, "--memory", "2g", "--pids-limit", "512", image, "sleep", "infinity"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _out, err = await proc.communicate()
        if proc.returncode != 0:
            raise SandboxError(f"failed to start session container:\n{err.decode(errors='replace')}")
        self._session_container = name
        import atexit
        atexit.register(self.close_session)  # best-effort cleanup on normal exit
        return name

    async def exec_in_session(self, image: str, argv: list[str], *,
                              timeout: float | None = None,
                              workspace: str | Path | None = None) -> SandboxResult:
        name = await self._ensure_session(image, workspace)
        cmd = [self.docker_bin, "exec", "-w", "/workspace", name, *argv]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout or self.default_timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise SandboxError(f"sandbox timeout after {timeout or self.default_timeout}s")
        return SandboxResult(proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))

    def close_session(self) -> None:
        """Remove the session container (sync so it's callable from exit handlers/atexit).
        Only the host-mounted /workspace persists afterwards."""
        name, self._session_container = self._session_container, None
        if not name or not self.available():
            return
        import subprocess
        subprocess.run([self.docker_bin, "rm", "-f", name],
                       capture_output=True, check=False)

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
        drop_caps: bool = True,
    ) -> SandboxResult:
        if not self.available():
            raise SandboxError("docker not found on PATH")

        # Auto-build the HexHarness sandbox image from the packaged Dockerfile the first
        # time it's needed, so the tooled Kali travels with the pip package.
        from hexharness.sandbox.image import build_image, image_exists, is_hexharness_image

        if is_hexharness_image(image) and not image_exists(image, docker_bin=self.docker_bin):
            ok, out = await build_image(image, docker_bin=self.docker_bin)
            if not ok:
                raise SandboxError(f"failed to build sandbox image {image}:\n{out}")

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

        # Capabilities. drop_caps=True (default, for scanners): drop ALL and add back only
        # what's asked (e.g. NET_RAW). drop_caps=False (for exec_command): keep Docker's
        # default caps so apt-get/dpkg and ordinary tooling work — the operator wants a
        # real working box there. --rm, pid/memory limits and the workspace mount still apply.
        cap_flags: list[str] = []
        for c in cap_add or []:
            cap_flags += ["--cap-add", c]
        if drop_caps:
            cap_flags = ["--cap-drop", "ALL", *cap_flags]
            security = [] if cap_add else ["--security-opt", "no-new-privileges"]
        else:
            security = []  # default caps; allow setuid helpers (apt/dpkg)
        cmd = [
            self.docker_bin, "run", "--rm",
            "--network", network,
            *security,
            *cap_flags,
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
