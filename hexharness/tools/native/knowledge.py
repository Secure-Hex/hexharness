"""Passive knowledge lookup. Read-only, not scope-sensitive — safe in any phase.

A tiny built-in CWE table today; the full MITRE ATT&CK/CWE + RAG knowledge layer is a
later phase. Still a real tool (static reference data), not a mock.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

_CWE = {
    "79": ("Cross-site Scripting (XSS)", "Improper neutralization of input during web page generation."),
    "89": ("SQL Injection", "Improper neutralization of special elements used in an SQL command."),
    "22": ("Path Traversal", "Improper limitation of a pathname to a restricted directory."),
    "78": ("OS Command Injection", "Improper neutralization of special elements used in an OS command."),
    "352": ("Cross-Site Request Forgery (CSRF)", "Web app does not verify a request was intentionally sent."),
    "287": ("Improper Authentication", "Incorrect proof of identity verification."),
}


class CweLookupInput(BaseModel):
    cwe_id: str = Field(description="CWE numeric id, e.g. '79' or 'CWE-79'")


class CweLookupTool(Tool):
    name = "cwe_lookup"
    description = "Look up a CWE weakness by id. Returns its name and a one-line description."
    input_model = CweLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        cid = str(tool_input.get("cwe_id", "")).upper().replace("CWE-", "").strip()
        entry = _CWE.get(cid)
        if not entry:
            return f"CWE-{cid}: not in local table. Known: {', '.join(sorted(_CWE))}"
        name, desc = entry
        return f"CWE-{cid} — {name}: {desc}"
