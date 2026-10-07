"""Service-probe tools: banner grab, anonymous-FTP check, SSH banner, HTTP probe.

All ACTIVE and scope_sensitive (the Scope Guard validates `host`/`url` before run()),
no approval. Each takes an INJECTABLE transport so tests need no network:

- BannerGrabTool / SshInfoTool: `connect_fn(host, port, timeout) -> socket-like`
  (default: stdlib socket.create_connection).
- FtpCheckTool: `ftp_factory() -> ftplib.FTP-like` (default: real ftplib.FTP).
- HttpProbeTool: `opener(url, timeout) -> response-like` (default: urllib.request.urlopen).

Failures are returned as text to the agent, never raised — same convention as web_search.
"""
from __future__ import annotations

import asyncio
import ftplib
import re
import socket
import urllib.request
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

# ponytail: socket-like is anything with sendall/recv/close; typing it as object keeps
# the inject hook honest without a Protocol nobody else needs.
ConnectFn = Callable[[str, int, int], object]

_SECURITY_HEADERS = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
)
_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _default_connect(host: str, port: int, timeout: int) -> socket.socket:
    return socket.create_connection((host, port), timeout=timeout)


class BannerGrabInput(BaseModel):
    host: str = Field(description="Host/IP to connect to (must be in engagement scope)")
    port: int = Field(ge=1, le=65535, description="TCP port")
    timeout: int = Field(default=5, ge=1, le=120)
    probe: str = Field(default="", description="Optional bytes to send before reading (e.g. a request line)")


class BannerGrabTool(Tool):
    name = "banner_grab"
    description = "Open a TCP connection, optionally send a probe, and read the service banner (~2KB)."
    input_model = BannerGrabInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    def __init__(self, *, connect_fn: ConnectFn | None = None):
        self._connect = connect_fn or _default_connect

    async def run(self, tool_input: dict) -> str:
        data = BannerGrabInput.model_validate(tool_input)
        return await asyncio.to_thread(self._grab, data)

    def _grab(self, data: BannerGrabInput) -> str:
        try:
            sock = self._connect(data.host, data.port, data.timeout)
            try:
                if data.probe:
                    sock.sendall(data.probe.encode())
                chunk = sock.recv(2048)
            finally:
                sock.close()
        except Exception as exc:  # noqa: BLE001 — surface to the agent, don't crash the loop
            return f"banner_grab {data.host}:{data.port}: error: {exc}"
        banner = chunk.decode(errors="replace").strip()
        return f"{data.host}:{data.port} banner:\n{banner}" if banner else f"{data.host}:{data.port}: no banner"


class FtpCheckInput(BaseModel):
    host: str = Field(description="FTP host/IP (must be in engagement scope)")
    port: int = Field(default=21, ge=1, le=65535)


class FtpCheckTool(Tool):
    name = "ftp_check"
    description = "Attempt an anonymous FTP login and list the root directory."
    input_model = FtpCheckInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    def __init__(self, *, ftp_factory: Callable[[], ftplib.FTP] | None = None):
        self._ftp_factory = ftp_factory or ftplib.FTP

    async def run(self, tool_input: dict) -> str:
        data = FtpCheckInput.model_validate(tool_input)
        return await asyncio.to_thread(self._check, data)

    def _check(self, data: FtpCheckInput) -> str:
        ftp = self._ftp_factory()
        try:
            ftp.connect(data.host, data.port)
            ftp.login()  # no creds => ftplib logs in as "anonymous"
            names = ftp.nlst()
        except Exception as exc:  # noqa: BLE001 — a refused login is a normal, reportable result
            return f"ftp {data.host}:{data.port}: anonymous login failed: {exc}"
        finally:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001 — best-effort close
                pass
        listing = "\n".join(f"  {n}" for n in names) if names else "  (empty)"
        return f"ftp {data.host}:{data.port}: ANONYMOUS login OK, {len(names)} entries:\n{listing}"


class SshInfoInput(BaseModel):
    host: str = Field(description="SSH host/IP (must be in engagement scope)")
    port: int = Field(default=22, ge=1, le=65535)


class SshInfoTool(Tool):
    name = "ssh_info"
    description = "Read the SSH identification banner (e.g. 'SSH-2.0-OpenSSH_9.6')."
    input_model = SshInfoInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    # ponytail: banner only. Auth-method / key-exchange probing would need paramiko — out of scope.
    def __init__(self, *, connect_fn: ConnectFn | None = None):
        self._connect = connect_fn or _default_connect

    async def run(self, tool_input: dict) -> str:
        data = SshInfoInput.model_validate(tool_input)
        return await asyncio.to_thread(self._banner, data)

    def _banner(self, data: SshInfoInput) -> str:
        try:
            sock = self._connect(data.host, data.port, 5)
            try:
                chunk = sock.recv(512)  # server speaks first on SSH
            finally:
                sock.close()
        except Exception as exc:  # noqa: BLE001 — surface to the agent
            return f"ssh_info {data.host}:{data.port}: error: {exc}"
        line = chunk.decode(errors="replace").splitlines()[0].strip() if chunk else ""
        return f"{data.host}:{data.port} {line}" if line else f"{data.host}:{data.port}: no SSH banner"


class HttpProbeInput(BaseModel):
    url: str = Field(description="Full URL to GET (host must be in engagement scope)")
    timeout: int = Field(default=10, ge=1, le=120)


class HttpProbeTool(Tool):
    name = "http_probe"
    description = "GET a URL and report status, key/security response headers, and the page <title>."
    input_model = HttpProbeInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "url"  # Scope Guard parses the host out of the URL itself

    def __init__(self, *, opener: Callable[[str, int], object] | None = None):
        self._opener = opener or (lambda url, timeout: urllib.request.urlopen(url, timeout=timeout))  # noqa: S310

    async def run(self, tool_input: dict) -> str:
        data = HttpProbeInput.model_validate(tool_input)
        return await asyncio.to_thread(self._probe, data)

    def _probe(self, data: HttpProbeInput) -> str:
        try:
            resp = self._opener(data.url, data.timeout)
            status = resp.status
            headers = resp.headers
            body = resp.read()
        except Exception as exc:  # noqa: BLE001 — surface to the agent
            return f"http_probe {data.url}: error: {exc}"

        lines = [f"GET {data.url} -> {status}"]
        for h in ("Server", "X-Powered-By", "Content-Type"):
            if (v := headers.get(h)) is not None:
                lines.append(f"{h}: {v}")
        lines.append(f"Set-Cookie: {'present' if headers.get('Set-Cookie') is not None else 'absent'}")
        sec = [f"{h}={'present' if headers.get(h) is not None else 'ABSENT'}" for h in _SECURITY_HEADERS]
        lines.append("Security headers: " + ", ".join(sec))
        m = _TITLE_RE.search(body if isinstance(body, bytes) else str(body).encode())
        if m:
            lines.append(f"<title>: {m.group(1).decode(errors='replace').strip()}")
        return "\n".join(lines)
