from __future__ import annotations

from hexharness.sandbox.executor import SandboxResult
from hexharness.tools.base import RiskLevel
from hexharness.tools.native.recon import DnsEnumTool, SmbEnumTool, WhoisLookupTool

SMB_OUTPUT = """
	Sharename       Type      Comment
	---------       ----      -------
	print$          Disk      Printer Drivers
	shared          Disk      Company share with spaces
	IPC$            IPC       IPC Service (server)

	Server               Comment
	---------            -------
"""

WHOIS_OUTPUT = """
Domain Name: example.com
Registrar: Example Registrar, Inc.
Creation Date: 1995-08-14T04:00:00Z
Registry Expiry Date: 2025-08-13T04:00:00Z
Name Server: a.iana-servers.net
Name Server: b.iana-servers.net
>>> Last update of whois database: 2024-01-01 <<<
"""


class FakeExecutor:
    """Records each sandbox call and returns a canned result. available() is True
    so tools take the real path; swap `avail` to exercise the graceful branch."""

    def __init__(self, result: SandboxResult, *, avail: bool = True):
        self.result = result
        self.avail = avail
        self.calls: list[tuple[str, list, str, object]] = []

    def available(self) -> bool:
        return self.avail

    async def run(self, image, argv, *, network="none", timeout=None, memory="512m", pids_limit=256):
        self.calls.append((image, argv, network, timeout))
        return self.result


# --- DnsEnumTool ---------------------------------------------------------

async def test_dns_enum_builds_dig_argv_per_type_and_parses():
    fake = FakeExecutor(SandboxResult(0, "93.184.216.34\n", ""))
    tool = DnsEnumTool(fake, image="kalilinux/kali-rolling")
    out = await tool.run({"host": "example.com", "record_types": ["A", "MX"]})

    assert [c[1] for c in fake.calls] == [
        ["dig", "+short", "example.com", "A"],
        ["dig", "+short", "example.com", "MX"],
    ]
    # scope target reaches the sandbox, as a list, over the bridge network.
    for image, argv, network, _ in fake.calls:
        assert image == "kalilinux/kali-rolling"
        assert isinstance(argv, list) and "example.com" in argv
        assert network == "bridge"
    assert "A: 93.184.216.34" in out
    assert "MX: 93.184.216.34" in out


async def test_dns_enum_scope_fields():
    assert DnsEnumTool().scope_sensitive is True
    assert DnsEnumTool().target_field == "host"
    assert DnsEnumTool().risk_level == RiskLevel.ACTIVE
    assert DnsEnumTool().requires_approval is False


# --- SmbEnumTool ---------------------------------------------------------

async def test_smb_enum_builds_argv_and_parses_shares():
    fake = FakeExecutor(SandboxResult(0, SMB_OUTPUT, ""))
    tool = SmbEnumTool(fake)
    out = await tool.run({"host": "10.0.0.5"})

    image, argv, network, _ = fake.calls[0]
    assert argv == ["smbclient", "-L", "//10.0.0.5", "-N"]
    assert network == "bridge"
    assert "print$" in out
    assert "shared" in out
    assert "Company share with spaces" in out  # comment with spaces survives
    assert "IPC$" in out


async def test_smb_enum_reports_failure():
    fake = FakeExecutor(SandboxResult(1, "", "NT_STATUS_CONNECTION_REFUSED"))
    out = await SmbEnumTool(fake).run({"host": "10.0.0.9"})
    assert "failed" in out and "NT_STATUS_CONNECTION_REFUSED" in out


async def test_smb_enum_scope_and_approval_fields():
    tool = SmbEnumTool()
    assert tool.risk_level == RiskLevel.INTRUSIVE
    assert tool.requires_approval is True
    assert tool.scope_sensitive is True
    assert tool.target_field == "host"


# --- WhoisLookupTool -----------------------------------------------------

async def test_whois_builds_argv_and_summarizes():
    fake = FakeExecutor(SandboxResult(0, WHOIS_OUTPUT, ""))
    out = await WhoisLookupTool(fake).run({"domain": "example.com"})

    image, argv, network, _ = fake.calls[0]
    assert argv == ["whois", "example.com"]
    assert network == "bridge"
    assert "Example Registrar, Inc." in out
    assert "1995-08-14T04:00:00Z" in out       # creation
    assert "2025-08-13T04:00:00Z" in out       # expiry
    assert "a.iana-servers.net" in out and "b.iana-servers.net" in out
    assert "raw tail:" in out


async def test_whois_scope_fields():
    tool = WhoisLookupTool()
    assert tool.risk_level == RiskLevel.PASSIVE
    assert tool.scope_sensitive is True
    assert tool.target_field == "domain"
    assert tool.requires_approval is False


# --- docker unavailable --------------------------------------------------

async def test_graceful_when_docker_unavailable():
    fake = FakeExecutor(SandboxResult(0, "", ""), avail=False)
    for tool, inp in (
        (DnsEnumTool(fake), {"host": "example.com"}),
        (SmbEnumTool(fake), {"host": "10.0.0.5"}),
        (WhoisLookupTool(fake), {"domain": "example.com"}),
    ):
        out = await tool.run(inp)
        assert "docker not available" in out
    assert fake.calls == []  # never touched the sandbox
