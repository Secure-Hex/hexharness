"""Scope Guard — the hard gate. Invariant #3: NO mode bypasses it, not even BYPASS.
There is no flag that turns it off. Target out of scope => deny, always. Fail-closed:
an unparseable target, or a target matching no allow rule, is denied."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse


def _host_of(target: str) -> str:
    t = target.strip()
    if "://" in t:
        t = urlparse(t).hostname or ""
    # strip any :port
    if t.count(":") == 1 and not _is_ip(t):
        t = t.split(":", 1)[0]
    return t.lower().rstrip(".")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _domain_matches(host: str, rule: str) -> bool:
    rule = rule.lower().lstrip("*.").rstrip(".")
    return host == rule or host.endswith("." + rule)


@dataclass(frozen=True)
class Scope:
    cidrs: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()  # domains or CIDRs; always win


@dataclass(frozen=True)
class ScopeGuard:
    scope: Scope
    _nets: list = field(default_factory=list, compare=False)
    _excl_nets: list = field(default_factory=list, compare=False)

    @classmethod
    def from_scope(cls, scope: Scope) -> "ScopeGuard":
        nets = [ipaddress.ip_network(c, strict=False) for c in scope.cidrs]
        excl_nets = [
            ipaddress.ip_network(e, strict=False) for e in scope.exclusions if _looks_cidr(e)
        ]
        return cls(scope=scope, _nets=nets, _excl_nets=excl_nets)

    def in_scope(self, target: str | None) -> bool:
        # Fail-closed: no target to check against a scope-sensitive action => deny.
        if not target:
            return False
        host = _host_of(target)
        if not host:
            return False

        if _is_ip(host):
            ip = ipaddress.ip_address(host)
            if any(ip in n for n in self._excl_nets):
                return False
            return any(ip in n for n in self._nets)

        # hostname path
        excl_domains = [e for e in self.scope.exclusions if not _looks_cidr(e)]
        if any(_domain_matches(host, e) for e in excl_domains):
            return False
        return any(_domain_matches(host, d) for d in self.scope.domains)


def _looks_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False
