"""Service-probe tools parse canned transport output with no network. Fakes are injected
for every tool; scope_sensitive/target_field/extract_target are asserted per tool."""
from __future__ import annotations

from email.message import Message

from hexharness.tools.native.services import (
    BannerGrabTool,
    FtpCheckTool,
    HttpProbeTool,
    SshInfoTool,
)


class FakeSocket:
    def __init__(self, data: bytes):
        self._data = data
        self.sent = b""
    def sendall(self, b): self.sent += b
    def recv(self, n): return self._data[:n]
    def close(self): pass


class FakeFtp:
    def __init__(self, names, *, fail: str | None = None):
        self._names, self._fail = names, fail
        self.connected = self.logged_in = self.quit_called = False
    def connect(self, host, port): self.connected = (host, port)
    def login(self, *a):
        if self._fail:
            raise OSError(self._fail)
        self.logged_in = True
    def nlst(self): return self._names
    def quit(self): self.quit_called = True


class FakeResponse:
    def __init__(self, status, headers: dict, body: bytes):
        self.status = status
        self.headers = Message()  # real HTTPMessage type => case-insensitive .get
        for k, v in headers.items():
            self.headers[k] = v
        self._body = body
    def read(self): return self._body


# --- BannerGrab -----------------------------------------------------------

async def test_banner_grab_sends_probe_and_decodes():
    sock = FakeSocket(b"220 vsFTPd 3.0.3 ready\r\n")
    tool = BannerGrabTool(connect_fn=lambda h, p, t: sock)
    out = await tool.run({"host": "10.0.0.5", "port": 21, "probe": "HELP\r\n"})
    assert "220 vsFTPd 3.0.3 ready" in out
    assert sock.sent == b"HELP\r\n"
    assert "10.0.0.5:21" in out


async def test_banner_grab_no_banner():
    tool = BannerGrabTool(connect_fn=lambda h, p, t: FakeSocket(b""))
    out = await tool.run({"host": "10.0.0.5", "port": 9999})
    assert "no banner" in out


def test_banner_grab_scope_fields():
    t = BannerGrabTool()
    assert t.risk_level.name == "ACTIVE"
    assert t.scope_sensitive is True and t.requires_approval is False
    assert t.target_field == "host"
    assert t.extract_target({"host": "10.0.0.5", "port": 21}) == "10.0.0.5"


# --- FtpCheck -------------------------------------------------------------

async def test_ftp_check_anonymous_success_lists_root():
    ftp = FakeFtp(["pub", "incoming", "readme.txt"])
    tool = FtpCheckTool(ftp_factory=lambda: ftp)
    out = await tool.run({"host": "10.0.0.7"})
    assert "ANONYMOUS login OK" in out and "3 entries" in out
    assert "readme.txt" in out
    assert ftp.connected == ("10.0.0.7", 21) and ftp.quit_called is True


async def test_ftp_check_login_refused():
    tool = FtpCheckTool(ftp_factory=lambda: FakeFtp([], fail="530 Login incorrect"))
    out = await tool.run({"host": "10.0.0.7"})
    assert "anonymous login failed" in out and "530" in out


def test_ftp_check_scope_fields():
    t = FtpCheckTool()
    assert t.risk_level.name == "ACTIVE"
    assert t.scope_sensitive is True and t.target_field == "host"
    assert t.extract_target({"host": "10.0.0.7"}) == "10.0.0.7"


# --- SshInfo --------------------------------------------------------------

async def test_ssh_info_reads_banner_line():
    sock = FakeSocket(b"SSH-2.0-OpenSSH_9.6\r\nrest\r\n")
    tool = SshInfoTool(connect_fn=lambda h, p, t: sock)
    out = await tool.run({"host": "10.0.0.9"})
    assert out == "10.0.0.9:22 SSH-2.0-OpenSSH_9.6"


def test_ssh_info_scope_fields():
    t = SshInfoTool()
    assert t.risk_level.name == "ACTIVE"
    assert t.scope_sensitive is True and t.target_field == "host"
    assert t.extract_target({"host": "10.0.0.9"}) == "10.0.0.9"


# --- HttpProbe ------------------------------------------------------------

async def test_http_probe_reports_status_headers_and_title():
    resp = FakeResponse(
        200,
        {"Server": "nginx/1.25", "Content-Type": "text/html", "Set-Cookie": "sid=abc",
         "X-Frame-Options": "DENY"},
        b"<html><head><title>Admin Portal</title></head></html>",
    )
    tool = HttpProbeTool(opener=lambda url, timeout: resp)
    out = await tool.run({"url": "http://example.com/"})
    assert "-> 200" in out
    assert "Server: nginx/1.25" in out
    assert "Set-Cookie: present" in out
    assert "X-Frame-Options=present" in out
    assert "Strict-Transport-Security=ABSENT" in out  # not supplied
    assert "<title>: Admin Portal" in out


def test_http_probe_scope_fields_and_target_is_url():
    t = HttpProbeTool()
    assert t.risk_level.name == "ACTIVE"
    assert t.scope_sensitive is True and t.requires_approval is False
    assert t.target_field == "url"
    assert t.extract_target({"url": "http://example.com/x"}) == "http://example.com/x"
