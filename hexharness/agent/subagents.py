"""Worker roles for the orchestrator-worker split (phase 8).

A role is pure data: a name, a system prompt, the phase it runs in, and a tool
filter deciding which tools the worker is even shown. The control plane still
gates every call at runtime — the filter just stops a worker from seeing tools
that don't belong to its phase/role (less to hallucinate, smaller prompt).

The default filter keeps tools whose risk fits the role's phase ceiling, so a
RECON worker only ever sees passive tools, etc. That ceiling is the same one
`Mode.decide` enforces, so filter and control plane never disagree.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hexharness.control.policy import Mode, Phase
from hexharness.tools.base import Tool


@dataclass(frozen=True)
class Role:
    name: str
    system_prompt: str
    default_phase: Phase
    tool_filter: Callable[[Tool], bool]


def _phase_filter(phase: Phase) -> Callable[[Tool], bool]:
    # ponytail: visibility == phase risk ceiling. Refine per-role by name/tag if a
    # worker ever needs a narrower slice than its whole phase.
    ceiling = Mode(phase=phase).phase_ceiling()
    return lambda tool: tool.risk_level <= ceiling


RECON = Role(
    name="recon",
    system_prompt=(
        "You are the RECON worker. Passively gather open-source and read-only "
        "information about in-scope targets. Never touch a target actively."
    ),
    default_phase=Phase.RECON,
    tool_filter=_phase_filter(Phase.RECON),
)

WEBAPP = Role(
    name="webapp",
    system_prompt=(
        "You are the WEBAPP worker. Enumerate and test web applications for "
        "common weaknesses (injection, auth, access control). Stay in scope."
    ),
    default_phase=Phase.EXPLOITATION,
    tool_filter=_phase_filter(Phase.EXPLOITATION),
)

NETWORK = Role(
    name="network",
    system_prompt=(
        "You are the NETWORK worker. Enumerate hosts, services and banners for "
        "in-scope networks. Active but non-intrusive probing only."
    ),
    default_phase=Phase.ENUMERATION,
    tool_filter=_phase_filter(Phase.ENUMERATION),
)

EXPLOITATION = Role(
    name="exploitation",
    system_prompt=(
        "You are the EXPLOITATION worker. Attempt to confirm vulnerabilities on "
        "in-scope targets with the least intrusive proof-of-concept possible."
    ),
    default_phase=Phase.EXPLOITATION,
    tool_filter=_phase_filter(Phase.EXPLOITATION),
)

POST_EXPLOITATION = Role(
    name="post_exploitation",
    system_prompt=(
        "You are the POST-EXPLOITATION worker. From an established foothold, "
        "enumerate access and demonstrate impact without destroying data."
    ),
    default_phase=Phase.POST_EXPLOITATION,
    tool_filter=_phase_filter(Phase.POST_EXPLOITATION),
)

REPORTING = Role(
    name="reporting",
    system_prompt=(
        "You are the REPORTING worker. Synthesize findings into a clear, "
        "evidence-backed report. Read-only — gather, never act on targets."
    ),
    default_phase=Phase.REPORTING,
    tool_filter=_phase_filter(Phase.REPORTING),
)

# Looked up by the lowercase role name the orchestrator plan emits.
ROLES: dict[str, Role] = {
    r.name: r for r in (RECON, WEBAPP, NETWORK, EXPLOITATION, POST_EXPLOITATION, REPORTING)
}
