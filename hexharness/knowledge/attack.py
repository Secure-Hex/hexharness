"""Passive MITRE ATT&CK technique lookup. Read-only, not scope-sensitive — safe in
any phase. Backed by a bundled JSON of common techniques (id/name/tactic/description).

# ponytail: static JSON, not the full ATT&CK STIX bundle. Swap the data file for the
# official enterprise-attack.json if full coverage is ever needed — loader stays.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

_DATA = Path(__file__).parent / "data" / "attack_techniques.json"


@lru_cache(maxsize=1)
def _techniques() -> list[dict]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


class MitreAttackInput(BaseModel):
    query: str = Field(description="ATT&CK technique id (e.g. 'T1059') or a keyword to search names/descriptions")


class MitreAttackTool(Tool):
    name = "mitre_attack_lookup"
    description = (
        "Look up MITRE ATT&CK techniques by id (e.g. 'T1059') or keyword. "
        "Returns matching technique id, name, tactic, and a short description."
    )
    input_model = MitreAttackInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        q = str(tool_input.get("query", "")).strip()
        if not q:
            return "mitre_attack_lookup: empty query."
        techs = _techniques()

        # Exact id match first (T1059, t1059, 1059 all accepted).
        qid = q.upper().lstrip("T")
        for t in techs:
            if t["id"].lstrip("T") == qid:
                return _fmt(t)

        # Otherwise keyword search over id/name/tactic/description.
        ql = q.lower()
        hits = [t for t in techs if ql in (f"{t['id']} {t['name']} {t['tactic']} {t['description']}").lower()]
        if not hits:
            return f"No ATT&CK technique matched '{q}'. Known ids: {', '.join(t['id'] for t in techs)}"
        return "\n".join(_fmt(t) for t in hits[:5])


def _fmt(t: dict) -> str:
    return f"{t['id']} — {t['name']} [{t['tactic']}]: {t['description']}"
