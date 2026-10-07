"""Recon tools: native DNS/WHOIS (injected), sandboxed SMB (fake executor). No net/docker."""
from __future__ import annotations

from dataclasses import dataclass

from hexharness.tools.base import RiskLevel
from hexharness.tools.native.recon import DnsEnumTool, SmbEnumTool, WhoisLookupTool


# --- DNS (native resolver injected) ---

async def test_dns_enum_uses_injected_resolver():
    calls = []

    def fake_resolve(host, rtype):
        calls.append((host, rtype))
        return {"A": ["69.6.225.245"], "MX": ["10 mail.x."]}.get(rtype, [])

    out = await DnsEnumTool(resolve_fn=fake_resolve).run({"host": "securehex.cl", "record_types": ["A", "MX", "NS"]})
    assert "A: 69.6.225.245" in out and "MX: 10 mail.x." in out and "NS: (none)" in out
    assert ("securehex.cl", "A") in calls


def test_dns_enum_fields():
    t = DnsEnumTool()
    assert t.scope_sensitive and t.target_field == "host" and t.risk_level is RiskLevel.ACTIVE


# --- WHOIS (native query injected) ---

async def test_whois_parses_injected_output():
    raw = ("Registrar: NIC Chile\nCreation Date: 2010-01-02\n"
           "Registry Expiry Date: 2030-01-02\nName Server: a.nic.cl\nName Server: b.nic.cl\n")
    out = await WhoisLookupTool(query_fn=lambda d: raw).run({"domain": "securehex.cl"})
    assert "registrar: NIC Chile" in out
    assert "a.nic.cl" in out and "b.nic.cl" in out


def test_whois_fields():
    t = WhoisLookupTool()
    assert t.scope_sensitive and t.target_field == "domain" and t.risk_level is RiskLevel.PASSIVE


# --- SMB (fake sandbox executor) ---

@dataclass
class _Res:
    exit_code: int
    stdout: str
    stderr: str = ""
    @property
    def ok(self):
        return self.exit_code == 0


class _FakeExec:
    def __init__(self, res):
        self._res = res
        self.calls = []
    def available(self):
        return True
    async def run(self, image, argv, **kw):
        self.calls.append((image, argv, kw))
        return self._res


async def test_smb_enum_builds_argv_and_parses():
    out_text = ("\n\tSharename       Type      Comment\n\t---------       ----      -------\n"
                "\tADMIN$          Disk      Remote Admin\n\tpublic          Disk      Public files\n\n")
    ex = _FakeExec(_Res(0, out_text))
    tool = SmbEnumTool(ex)
    out = await tool.run({"host": "10.0.0.5"})
    image, argv, kw = ex.calls[0]
    assert argv == ["smbclient", "-L", "//10.0.0.5", "-N"]
    assert "ADMIN$" in out and "public" in out
    assert tool.requires_approval and tool.risk_level is RiskLevel.INTRUSIVE


async def test_smb_enum_docker_unavailable():
    class _Down(_FakeExec):
        def available(self):
            return False
    out = await SmbEnumTool(_Down(_Res(0, ""))).run({"host": "10.0.0.5"})
    assert "docker not available" in out
