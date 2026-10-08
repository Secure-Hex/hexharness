"""Parallel multi-host nmap scan (sandboxed). INTRUSIVE, requires approval.

Multiple targets in one call, so the control plane can't check a single
`target_field` — that's WHY scope is enforced INSIDE this tool, fail-closed:
no scope_check => nothing runs; out-of-scope hosts are skipped, never scanned.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool

_DOCKER_UNAVAILABLE = "docker not available: sandbox cannot run (is docker on PATH?)"


class ParallelScanInput(BaseModel):
    hosts: list[str] = Field(description="Hosts/IPs to scan (each must be in engagement scope)")
    ports: str = Field(default="1-1000", description="nmap port spec, e.g. '22,80,443' or '1-1000'")
    flags: list[str] = Field(
        default_factory=lambda: ["-sS", "-Pn"],
        description="nmap flags applied to every host (default SYN scan -sS -Pn).",
    )
    timeout: int = Field(default=300, description="Per-host scan timeout in seconds")


class ParallelScanTool(Tool):
    name = "parallel_scan"
    description = (
        "nmap port scan across MANY hosts concurrently (sandboxed, raw sockets). "
        "Out-of-scope hosts are skipped automatically. Intrusive — requires approval."
    )
    input_model = ParallelScanInput
    risk_level = RiskLevel.INTRUSIVE
    # Not scope_sensitive: multiple targets, no single target_field for the control
    # plane to check — scope is enforced internally via scope_check (fail-closed).
    scope_sensitive = False
    requires_approval = True

    def __init__(self, executor: SandboxExecutor | None = None, *,
                 scope_check: Callable[[str], bool] | None = None,
                 image: str = "hexharness/kali:latest", max_concurrency: int = 5):
        self.executor = executor or SandboxExecutor()
        self.scope_check = scope_check
        self.image = image
        self.max_concurrency = max_concurrency

    async def run(self, tool_input: dict) -> str:
        # Fail-closed: without a scope check we cannot prove any host is in scope.
        if self.scope_check is None:
            return "refused: no scope check wired — running nothing (fail-closed)"
        if not self.executor.available():
            return _DOCKER_UNAVAILABLE

        hosts = list(tool_input.get("hosts") or [])
        ports = tool_input.get("ports", "1-1000")
        flags = list(tool_input.get("flags") or ["-sS", "-Pn"])
        timeout = tool_input.get("timeout", 300)

        in_scope = [h for h in hosts if self.scope_check(h)]
        skipped = [h for h in hosts if not self.scope_check(h)]

        sem = asyncio.Semaphore(self.max_concurrency)

        async def scan(host: str) -> str:
            async with sem:
                # Same argv/caps as PortScanTool: program name leads the list (no entrypoint),
                # NET_RAW for SYN/OS scans, bridge network. Host is scope-checked above.
                r = await self.executor.run(
                    self.image, ["nmap", *flags, "-p", ports, host],
                    network="bridge", timeout=timeout, cap_add=["NET_RAW"],
                )
                body = r.stdout if r.ok else f"scan failed (exit {r.exit_code}): {r.stderr}"
                return f"=== {host} ===\n{body}"

        results = await asyncio.gather(*(scan(h) for h in in_scope))

        parts = list(results)
        for h in skipped:
            parts.append(f"=== {h} ===\nskipped (out of scope)")
        return "\n\n".join(parts) if parts else "no hosts given"
