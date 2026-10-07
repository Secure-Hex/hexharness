"""shodan_host — look up a host on Shodan. Also the clearest demo of the out-of-band
secret flow: it declares required_secrets=["SHODAN_API_KEY"], so the first time it runs
the control plane prompts the operator for the key (masked, never shown to the model),
stores it in the Vault, and subsequent calls reuse it.
"""
from __future__ import annotations

import asyncio
import json
import socket
import urllib.parse
import urllib.request
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class ShodanHostInput(BaseModel):
    host: str = Field(description="IP or hostname to look up (must be in engagement scope)")


class ShodanHostTool(Tool):
    name = "shodan_host"
    description = (
        "Look up a host on Shodan (open ports, services, known vulns). Needs a Shodan API "
        "key — the operator is prompted for it once, out of band, if it isn't set yet."
    )
    input_model = ShodanHostInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    target_field = "host"
    requires_approval = False
    required_secrets = ["SHODAN_API_KEY"]  # the control plane resolves this before run()

    def __init__(self, vault, *, opener: Callable | None = None):
        self.vault = vault
        self._opener = opener  # inject for tests; default is urllib

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        key = self.vault.get("SHODAN_API_KEY")  # present: the control plane just ensured it
        try:
            ip = host if _is_ip(host) else socket.gethostbyname(host)
        except OSError as exc:
            return f"could not resolve {host}: {exc}"
        url = f"https://api.shodan.io/shodan/host/{ip}?key={urllib.parse.quote(key)}"
        try:
            data = await asyncio.to_thread(self._fetch, url)
        except Exception as exc:  # noqa: BLE001
            return f"shodan error: {exc}"
        ports = data.get("ports", [])
        vulns = data.get("vulns", [])
        svcs = [f"{s.get('port')}/{s.get('transport', 'tcp')} {s.get('product', '')}".strip()
                for s in data.get("data", [])][:15]
        out = [f"{ip} ({host}) — org: {data.get('org', '?')}, os: {data.get('os') or '?'}",
               f"ports: {', '.join(map(str, ports)) or 'none'}"]
        if svcs:
            out.append("services:\n  " + "\n  ".join(svcs))
        if vulns:
            out.append(f"vulns: {', '.join(sorted(vulns))}")
        return "\n".join(out)

    def _fetch(self, url: str) -> dict:
        if self._opener is not None:
            return self._opener(url)
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — fixed Shodan API host
            return json.loads(resp.read().decode())


def _is_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
