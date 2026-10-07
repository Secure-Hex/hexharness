"""Recon tools. DNS and WHOIS run NATIVELY (no sandbox), so they work regardless of
what the engagement's Docker image has installed (a bare kali image has no dig/whois).
SMB still shells smbclient in the sandbox. All three are scope-sensitive — the Scope
Guard checks the target field before they run.

- DnsEnumTool:     ACTIVE,    dnspython resolver (A/AAAA/MX/NS/TXT).
- WhoisLookupTool: PASSIVE,   raw WHOIS over TCP/43 with IANA referral (stdlib).
- SmbEnumTool:     INTRUSIVE, `smbclient -L` in the sandbox (needs smbclient in the image).
"""
from __future__ import annotations

import asyncio
import socket
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool

_DOCKER_UNAVAILABLE = "docker not available: sandbox cannot run (is docker on PATH?)"


# ---------------------------------------------------------------- DNS (native) --

class DnsEnumInput(BaseModel):
    host: str = Field(description="Hostname to enumerate (must be in engagement scope)")
    record_types: list[str] = Field(default=["A", "AAAA", "MX", "NS", "TXT"])


class DnsEnumTool(Tool):
    name = "dns_enum"
    description = "Enumerate DNS records (A/AAAA/MX/NS/TXT) for a host. Native resolver, no sandbox."
    input_model = DnsEnumInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    def __init__(self, *, resolve_fn: Callable[[str, str], list[str]] | None = None):
        self._resolve_fn = resolve_fn  # inject for tests; default uses dnspython

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        types = list(dict.fromkeys(tool_input.get("record_types") or ["A", "AAAA", "MX", "NS", "TXT"]))
        resolve = self._resolve_fn or _dnspython_resolve
        lines = [f"DNS records for {host}:"]
        for rtype in types:
            try:
                records = await asyncio.to_thread(resolve, host, rtype)
            except _MissingDnspython:
                return "dns_enum needs dnspython: pip install -e . (it is a core dependency)"
            except Exception as exc:  # noqa: BLE001 — NXDOMAIN/NoAnswer/timeout per type
                lines.append(f"  {rtype}: {type(exc).__name__}")
                continue
            lines.append(f"  {rtype}: {', '.join(records) if records else '(none)'}")
        return "\n".join(lines)


class _MissingDnspython(Exception):
    pass


def _dnspython_resolve(host: str, rtype: str) -> list[str]:
    try:
        import dns.resolver
    except ImportError as exc:  # noqa: BLE001
        raise _MissingDnspython from exc
    answer = dns.resolver.resolve(host, rtype, lifetime=10)
    return [r.to_text() for r in answer]


# -------------------------------------------------------------- WHOIS (native) --

class WhoisLookupInput(BaseModel):
    domain: str = Field(description="Domain to look up (must be in engagement scope)")


class WhoisLookupTool(Tool):
    name = "whois_lookup"
    description = "WHOIS registration lookup for a domain (raw WHOIS protocol, no sandbox)."
    input_model = WhoisLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "domain"

    def __init__(self, *, query_fn: Callable[[str], str] | None = None):
        self._query_fn = query_fn  # inject for tests; default = IANA-referral WHOIS

    async def run(self, tool_input: dict) -> str:
        domain = tool_input["domain"]
        query = self._query_fn or _iana_whois
        try:
            raw = await asyncio.to_thread(query, domain)
        except Exception as exc:  # noqa: BLE001
            return f"whois failed: {exc}"
        return _summarize_whois(domain, raw)


def _whois_query(query: str, server: str, timeout: int = 15) -> str:
    with socket.create_connection((server, 43), timeout=timeout) as s:
        s.sendall((query + "\r\n").encode())
        chunks = []
        while True:
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks).decode(errors="replace")


def _iana_whois(domain: str) -> str:
    """Ask IANA which WHOIS server owns the TLD, then query that server for the domain."""
    tld = domain.rsplit(".", 1)[-1]
    referral = _whois_query(tld, "whois.iana.org")
    server = next((ln.split(":", 1)[1].strip() for ln in referral.splitlines()
                   if ln.lower().startswith("refer:")), None)
    if not server:
        return referral
    return _whois_query(domain, server)


_WHOIS_FIELDS = {
    "registrar": ("registrar:",),
    "created": ("creation date:", "created:", "registered on:"),
    "expires": ("registry expiry date:", "expiry date:", "expires:", "expiration date:"),
}


def _summarize_whois(domain: str, stdout: str) -> str:
    found: dict[str, str] = {}
    name_servers: list[str] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        low = line.lower()
        for key, labels in _WHOIS_FIELDS.items():
            if key not in found and any(low.startswith(lbl) for lbl in labels):
                found[key] = line.split(":", 1)[1].strip()
        if low.startswith("name server:") or low.startswith("nserver:"):
            ns = line.split(":", 1)[1].strip()
            if ns and ns not in name_servers:
                name_servers.append(ns)
    out = [f"WHOIS for {domain}:",
           f"  registrar: {found.get('registrar', '(unknown)')}",
           f"  created: {found.get('created', '(unknown)')}",
           f"  expires: {found.get('expires', '(unknown)')}",
           f"  name servers: {', '.join(name_servers) if name_servers else '(unknown)'}",
           f"  raw tail:\n{stdout.strip()[-500:]}"]
    return "\n".join(out)


# ---------------------------------------------------------------- SMB (sandbox) --

class SmbEnumInput(BaseModel):
    host: str = Field(description="Host/IP to enumerate SMB shares on (must be in engagement scope)")


class SmbEnumTool(Tool):
    name = "smb_enum"
    description = "List SMB shares anonymously via smbclient (sandboxed). Intrusive — requires approval."
    input_model = SmbEnumInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = True
    requires_approval = True
    target_field = "host"

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "kalilinux/kali-rolling"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        if not self.executor.available():
            return _DOCKER_UNAVAILABLE
        host = tool_input["host"]
        result = await self.executor.run(
            self.image, ["smbclient", "-L", f"//{host}", "-N"], network="bridge", timeout=60
        )
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            hint = ("  (the sandbox image may lack smbclient — set a tooled image in the "
                    "engagement sandbox_image)" if "not found" in detail.lower() else "")
            return f"smb enum failed (exit {result.exit_code}): {detail}{hint}"
        shares = _parse_smb_shares(result.stdout)
        if not shares:
            return f"SMB shares on {host}: (none listed)"
        body = "\n".join(f"  {name}  {stype}  {comment}".rstrip() for name, stype, comment in shares)
        return f"SMB shares on {host}:\n{body}"


def _parse_smb_shares(stdout: str) -> list[tuple[str, str, str]]:
    lines = stdout.splitlines()
    shares: list[tuple[str, str, str]] = []
    header_idx = next((i for i, ln in enumerate(lines) if "Sharename" in ln and "Type" in ln), None)
    if header_idx is None:
        return shares
    header = lines[header_idx]
    type_at = header.find("Type")
    comment_at = header.find("Comment")
    for ln in lines[header_idx + 2:]:
        if not ln.strip():
            break
        name = ln[:type_at].strip()
        stype = ln[type_at:comment_at].strip() if comment_at > type_at else ln[type_at:].strip()
        comment = ln[comment_at:].strip() if comment_at > type_at else ""
        if name:
            shares.append((name, stype, comment))
    return shares
