"""ParallelScanTool: fake executor + fake scope_check. No net/docker."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from hexharness.tools.base import RiskLevel
from hexharness.tools.native.parallel import ParallelScanTool


@dataclass
class _Res:
    exit_code: int
    stdout: str
    stderr: str = ""
    @property
    def ok(self):
        return self.exit_code == 0


class _FakeExec:
    """Records calls, returns canned result, and tracks max in-flight concurrency."""
    def __init__(self, res, *, delay=0.01):
        self._res = res
        self._delay = delay
        self.calls = []
        self.current = 0
        self.max_seen = 0

    def available(self):
        return True

    async def run(self, image, argv, **kw):
        self.calls.append((image, argv, kw))
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)
        try:
            await asyncio.sleep(self._delay)  # hold the slot so concurrency can pile up
        finally:
            self.current -= 1
        return self._res


# in scope = anything starting with "10.", like the default CIDR
def _scope(host: str) -> bool:
    return host.startswith("10.")


async def test_in_scope_scanned_out_of_scope_skipped():
    ex = _FakeExec(_Res(0, "PORT 80/tcp open"))
    tool = ParallelScanTool(ex, scope_check=_scope)
    out = await tool.run({"hosts": ["10.0.0.1", "8.8.8.8", "10.0.0.2"]})
    scanned = {argv[-1] for _, argv, _ in ex.calls}
    assert scanned == {"10.0.0.1", "10.0.0.2"}          # only in-scope hosts ran
    assert "8.8.8.8 ===\nskipped (out of scope)" in out  # out-of-scope reported, not scanned
    assert "10.0.0.1" in out and "PORT 80/tcp open" in out


async def test_argv_leads_with_nmap_and_includes_host():
    ex = _FakeExec(_Res(0, "ok"))
    await ParallelScanTool(ex, scope_check=_scope).run(
        {"hosts": ["10.0.0.5"], "ports": "22,80", "flags": ["-sS", "-Pn"]})
    _, argv, kw = ex.calls[0]
    assert argv[0] == "nmap" and "10.0.0.5" in argv
    assert argv == ["nmap", "-sS", "-Pn", "-p", "22,80", "10.0.0.5"]
    assert kw["cap_add"] == ["NET_RAW"] and kw["network"] == "bridge"


async def test_no_scope_check_runs_nothing():
    ex = _FakeExec(_Res(0, "ok"))
    out = await ParallelScanTool(ex, scope_check=None).run({"hosts": ["10.0.0.1"]})
    assert ex.calls == []            # fail-closed: nothing executed
    assert "fail-closed" in out


async def test_concurrency_is_bounded():
    ex = _FakeExec(_Res(0, "ok"))
    hosts = [f"10.0.0.{i}" for i in range(12)]
    await ParallelScanTool(ex, scope_check=_scope, max_concurrency=5).run({"hosts": hosts})
    assert len(ex.calls) == 12
    assert ex.max_seen == 5          # bounded by the semaphore, and it DID reach the cap


def test_fields():
    t = ParallelScanTool(scope_check=_scope)
    assert t.risk_level is RiskLevel.INTRUSIVE
    assert t.requires_approval and t.scope_sensitive is False
