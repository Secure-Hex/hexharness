"""Recon tools that shell kali utilities inside the Docker sandbox.

All three are scope-sensitive — the Scope Guard checks the target field before
they run. argv is always built as a LIST (never a shell string), so a hostile
target string cannot inject a command.

- DnsEnumTool:     ACTIVE,    `dig +short` per record type.
- SmbEnumTool:     INTRUSIVE, `smbclient -L` anonymous share enumeration.
- WhoisLookupTool: PASSIVE,   `whois` registration lookup.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool

_DOCKER_UNAVAILABLE = "docker not available: sandbox cannot run (is docker on PATH?)"


class DnsEnumInput(BaseModel):
    host: str = Field(description="Hostname to enumerate (must be in engagement scope)")
    record_types: list[str] = Field(
        default=["A", "AAAA", "MX", "NS", "TXT"],
        description="DNS record types to query with dig",
    )


class DnsEnumTool(Tool):
    name = "dns_enum"
    description = "Enumerate DNS records (A/AAAA/MX/NS/TXT) for a host via dig (sandboxed)."
    input_model = DnsEnumInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "kalilinux/kali-rolling"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        if not self.executor.available():
            return _DOCKER_UNAVAILABLE
        host = tool_input["host"]
        # ponytail: one dig per record type. Bounded by record_types; dedupe keeps it sane.
        types = list(dict.fromkeys(tool_input.get("record_types") or ["A", "AAAA", "MX", "NS", "TXT"]))
        lines = [f"DNS records for {host}:"]
        for rtype in types:
            result = await self.executor.run(
                self.image, ["dig", "+short", host, rtype], network="bridge", timeout=30
            )
            if not result.ok:
                lines.append(f"  {rtype}: query failed (exit {result.exit_code})")
                continue
            records = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
            lines.append(f"  {rtype}: {', '.join(records) if records else '(none)'}")
        return "\n".join(lines)


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
            # smbclient writes the useful diagnostics to stderr (and sometimes stdout).
            detail = (result.stderr or result.stdout).strip()
            return f"smb enum failed (exit {result.exit_code}): {detail}"
        shares = _parse_smb_shares(result.stdout)
        if not shares:
            return f"SMB shares on {host}: (none listed)"
        body = "\n".join(f"  {name}  {stype}  {comment}".rstrip() for name, stype, comment in shares)
        return f"SMB shares on {host}:\n{body}"


def _parse_smb_shares(stdout: str) -> list[tuple[str, str, str]]:
    """Pull (name, type, comment) rows out of smbclient -L output.

    The share table sits between the 'Sharename ... Comment' header and the
    first blank line. ponytail: fixed-width columns, so slice by the header
    offsets rather than guessing at whitespace splits (comments contain spaces).
    """
    lines = stdout.splitlines()
    shares: list[tuple[str, str, str]] = []
    header_idx = next((i for i, ln in enumerate(lines) if "Sharename" in ln and "Type" in ln), None)
    if header_idx is None:
        return shares
    header = lines[header_idx]
    type_at = header.find("Type")
    comment_at = header.find("Comment")
    for ln in lines[header_idx + 2:]:  # skip header + the '---- ----' divider
        if not ln.strip():
            break  # table ends at the first blank line
        name = ln[:type_at].strip()
        stype = ln[type_at:comment_at].strip() if comment_at > type_at else ln[type_at:].strip()
        comment = ln[comment_at:].strip() if comment_at > type_at else ""
        if name:
            shares.append((name, stype, comment))
    return shares


class WhoisLookupInput(BaseModel):
    domain: str = Field(description="Domain to look up (must be in engagement scope)")


class WhoisLookupTool(Tool):
    name = "whois_lookup"
    description = "WHOIS registration lookup for a domain via whois (sandboxed)."
    input_model = WhoisLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "domain"

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "kalilinux/kali-rolling"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        if not self.executor.available():
            return _DOCKER_UNAVAILABLE
        domain = tool_input["domain"]
        result = await self.executor.run(
            self.image, ["whois", domain], network="bridge", timeout=60
        )
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            return f"whois failed (exit {result.exit_code}): {detail}"
        return _summarize_whois(domain, result.stdout)


# ponytail: substring match on key labels. Registrars vary wording wildly;
# this hits the common ones and the raw tail covers whatever it misses.
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
    out = [f"WHOIS for {domain}:"]
    out.append(f"  registrar: {found.get('registrar', '(unknown)')}")
    out.append(f"  created: {found.get('created', '(unknown)')}")
    out.append(f"  expires: {found.get('expires', '(unknown)')}")
    out.append(f"  name servers: {', '.join(name_servers) if name_servers else '(unknown)'}")
    tail = stdout.strip()[-500:]
    out.append(f"  raw tail:\n{tail}")
    return "\n".join(out)
