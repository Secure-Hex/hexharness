"""Slash skill references, like Claude Code's `/command`.

When a prompt starts with `/<skill>`, expand it by pulling that skill's playbook body
into the prompt so the model follows it for the task. `/` (or `/?`) lists the available
skills. Unknown skills are reported with the list, not silently run.
"""
from __future__ import annotations


def list_skills(registry) -> list[str]:
    return [m.name for m in registry.list_metadata()]


def is_list_request(text: str) -> bool:
    return text.strip() in ("/", "/?", "/help")


def expand_slash(text: str, registry) -> tuple[str, str | None, str | None]:
    """Return (expanded_text, used_skill, unknown_skill).

    - no leading slash  -> (text, None, None), unchanged.
    - `/known rest`     -> (playbook + task, "known", None).
    - `/unknown ...`     -> (text, None, "unknown").
    """
    text = text.strip()
    if not text.startswith("/"):
        return text, None, None
    first, _, rest = text.partition(" ")
    name = first[1:].strip()
    if not name:
        return text, None, None
    if name not in set(list_skills(registry)):
        return text, None, name
    body = registry.load(name)
    task = rest.strip()
    expanded = f"Follow this skill playbook:\n\n{body}"
    if task:
        expanded += f"\n\n---\nTask: {task}"
    return expanded, name, None
