"""Slash skill references expand the playbook into the prompt; unknown ones are flagged."""
from __future__ import annotations

from pathlib import Path

from hexharness.skills.engine import SkillRegistry
from hexharness.skills.slash import expand_slash, is_list_request, list_skills

_LIBRARY = Path(__file__).resolve().parent.parent / "hexharness" / "skills" / "library"


def _registry() -> SkillRegistry:
    return SkillRegistry().discover(_LIBRARY)


def test_lists_bundled_skills():
    names = list_skills(_registry())
    assert names  # the repo ships at least one skill
    assert is_list_request("/") and is_list_request("/help")


def test_known_skill_expands_with_body():
    reg = _registry()
    name = list_skills(reg)[0]
    expanded, used, unknown = expand_slash(f"/{name} map the perimeter", reg)
    assert used == name and unknown is None
    assert "Follow this skill playbook" in expanded
    assert "Task: map the perimeter" in expanded
    assert expanded != f"/{name} map the perimeter"  # actually expanded


def test_unknown_skill_flagged_not_run():
    expanded, used, unknown = expand_slash("/does-not-exist do stuff", _registry())
    assert unknown == "does-not-exist" and used is None
    assert expanded == "/does-not-exist do stuff"  # unchanged; caller warns instead of running


def test_plain_prompt_untouched():
    expanded, used, unknown = expand_slash("just resolve a host", _registry())
    assert (expanded, used, unknown) == ("just resolve a host", None, None)
