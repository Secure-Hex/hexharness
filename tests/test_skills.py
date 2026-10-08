from __future__ import annotations

import json
from pathlib import Path

from hexharness.skills.engine import SkillRegistry
from hexharness.skills.tool import SkillLookupTool
from hexharness.tools.base import RiskLevel

LIBRARY = Path(__file__).resolve().parents[1] / "hexharness" / "skills" / "library"


def _registry() -> SkillRegistry:
    return SkillRegistry().discover(LIBRARY)


def test_discover_lists_bundled_skills_cheaply() -> None:
    reg = _registry()
    names = {m.name for m in reg.list_metadata()}
    assert {"subdomain-enumeration", "sqli-triage", "workflow-chaining"} <= names
    # metadata is manifest-only — never the playbook body
    recon = next(m for m in reg.list_metadata() if m.name == "subdomain-enumeration")
    assert recon.phase == "recon"
    assert recon.description and "Playbook" not in recon.description


def test_load_returns_playbook_body() -> None:
    reg = _registry()
    body = reg.load("sqli-triage")
    assert "SQL Injection Triage" in body
    assert "Boolean differential" in body


def test_skill_tool_is_passive_and_not_scope_sensitive() -> None:
    tool = SkillLookupTool(_registry())
    assert tool.risk_level is RiskLevel.PASSIVE
    assert tool.scope_sensitive is False


async def test_skill_tool_lists_without_name() -> None:
    tool = SkillLookupTool(_registry())
    listing = json.loads(await tool.run({}))
    assert {"subdomain-enumeration", "sqli-triage", "workflow-chaining"} <= {entry["name"] for entry in listing}


async def test_skill_tool_returns_body_with_name() -> None:
    tool = SkillLookupTool(_registry())
    body = await tool.run({"skill_name": "subdomain-enumeration"})
    assert "Subdomain Enumeration" in body

    missing = await tool.run({"skill_name": "nope"})
    assert "unknown skill" in missing
