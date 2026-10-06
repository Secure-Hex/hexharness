"""Network tools. Both scope-sensitive — the Scope Guard checks `host` before they run.

- DnsLookupTool: ACTIVE, resolves a hostname (stdlib socket, real).
- PortScanTool: INTRUSIVE and requires_approval — runs nmap inside the Docker sandbox.
"""
from __future__ import annotations

import asyncio
import socket

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool


class DnsLookupInput(BaseModel):
    host: str = Field(description="Hostname to resolve (must be in engagement scope)")


class DnsLookupTool(Tool):
    name = "dns_lookup"
    description = "Resolve a hostname to its A/AAAA records."
    input_model = DnsLookupInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        addrs = sorted({i[4][0] for i in infos})
        return f"{host} -> {', '.join(addrs)}" if addrs else f"{host}: no records"


class PortScanInput(BaseModel):
    host: str = Field(description="Host/IP to scan (must be in engagement scope)")
    ports: str = Field(default="1-1000", description="nmap port spec, e.g. '22,80,443' or '1-1000'")


class PortScanTool(Tool):
    name = "port_scan"
    description = "TCP port scan via nmap (sandboxed). Intrusive — requires approval."
    input_model = PortScanInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = True
    requires_approval = True
    target_field = "host"

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "instrumentisto/nmap"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        ports = tool_input.get("ports", "1-1000")
        result = await self.executor.run(
            self.image, ["-p", ports, "-Pn", host], network="bridge", timeout=180
        )
        return result.stdout if result.ok else f"scan failed (exit {result.exit_code}): {result.stderr}"
