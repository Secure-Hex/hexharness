"""Invariant #3: Scope Guard is a hard gate NO mode bypasses, not even BYPASS.
Out of scope => deny, always. No target => deny (fail-closed)."""
from __future__ import annotations

from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.scope_guard import Scope, ScopeGuard
from hexharness.tools.base import RiskLevel

from tests._fakes import SpyTool
from tests.conftest import ctx, make_control

BYPASS = Mode(autonomy=Autonomy.BYPASS, phase=Phase.POST_EXPLOITATION)


async def test_out_of_scope_denied_even_in_bypass():
    cp, _ = make_control(scope=Scope(domains=("acme.example",)))
    tool = SpyTool("dns", RiskLevel.ACTIVE, scope_sensitive=True, target_field="host")
    d = await cp.authorize(ctx(BYPASS), tool, {"host": "evil.notacme.example"})
    assert d.effect.value == "deny"
    assert d.gate == "scope_guard"


async def test_in_scope_passes_scope_gate():
    cp, _ = make_control(scope=Scope(domains=("acme.example",)))
    tool = SpyTool("dns", RiskLevel.ACTIVE, scope_sensitive=True, target_field="host")
    d = await cp.authorize(ctx(BYPASS), tool, {"host": "www.acme.example"})
    assert d.allowed  # bypass + in scope + risk under ROE ceiling


async def test_missing_target_fail_closed():
    cp, _ = make_control(scope=Scope(domains=("acme.example",)))
    tool = SpyTool("dns", RiskLevel.ACTIVE, scope_sensitive=True, target_field="host")
    d = await cp.authorize(ctx(BYPASS), tool, {})  # no host
    assert d.effect.value == "deny"
    assert d.gate == "scope_guard"


async def test_exclusion_wins_over_allow():
    guard = ScopeGuard.from_scope(
        Scope(domains=("acme.example", "*.acme.example"), exclusions=("vpn.acme.example",))
    )
    assert guard.in_scope("app.acme.example") is True
    assert guard.in_scope("vpn.acme.example") is False


async def test_cidr_scope_and_exclusion():
    guard = ScopeGuard.from_scope(Scope(cidrs=("203.0.113.0/24",), exclusions=("203.0.113.1/32",)))
    assert guard.in_scope("203.0.113.50") is True
    assert guard.in_scope("203.0.113.1") is False
    assert guard.in_scope("198.51.100.9") is False
