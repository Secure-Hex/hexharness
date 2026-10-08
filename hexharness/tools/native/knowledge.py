"""Passive knowledge lookup. Read-only, not scope-sensitive — safe in any phase.

Backed by the FULL MITRE CWE catalog, bundled as a compact JSON (id -> [name, description]).
Regenerate from cwec_latest.xml when a newer CWE version is needed — the loader stays.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

_DATA = Path(__file__).parents[2] / "knowledge" / "data" / "cwe.json"


@lru_cache(maxsize=1)
def _cwe_table() -> dict[str, list[str]]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


class CweLookupInput(BaseModel):
    cwe_id: str = Field(description="CWE numeric id, e.g. '79' or 'CWE-79'")


class CweLookupTool(Tool):
    name = "cwe_lookup"
    description = "Look up a CWE weakness by id (full MITRE catalog). Returns its name and description."
    input_model = CweLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        cid = str(tool_input.get("cwe_id", "")).upper().replace("CWE-", "").strip()
        entry = _cwe_table().get(cid)
        if not entry:
            return f"CWE-{cid}: not a known CWE id (the full catalog has {len(_cwe_table())} entries)."
        name, desc = entry[0], entry[1]
        return f"CWE-{cid} — {name}: {desc}"
