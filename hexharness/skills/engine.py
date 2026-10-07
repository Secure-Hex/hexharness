"""Skill engine with progressive disclosure.

A skill is a directory holding a `skill.yaml` manifest (cheap metadata, always
loadable into context) plus a `playbook.md` body (the full prose, loaded only
when the skill is actually selected). Keeping the two apart is the whole point:
the agent sees every skill's one-line summary for free and pays the token cost
of a playbook only on demand.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

MANIFEST_FILE = "skill.yaml"
PLAYBOOK_FILE = "playbook.md"


class SkillManifest(BaseModel):
    """Cheap metadata parsed from a skill's `skill.yaml`. Stays in context."""

    name: str
    description: str
    version: str = "0.1.0"
    phase: str = Field(description="Engagement phase, e.g. 'recon' or 'webapp'.")
    tags: list[str] = Field(default_factory=list)
    risk_hint: str = Field(
        default="passive",
        description="Advisory risk posture of the playbook's actions; the control "
        "plane still authorizes each tool call independently.",
    )


class Skill:
    """A manifest plus a lazy handle to its playbook body."""

    def __init__(self, manifest: SkillManifest, playbook_path: Path) -> None:
        self.manifest = manifest
        self.playbook_path = playbook_path

    def metadata(self) -> SkillManifest:
        return self.manifest

    def body(self) -> str:
        # ponytail: read on demand; playbooks are small, so no caching layer.
        return self.playbook_path.read_text(encoding="utf-8")


class SkillRegistry:
    """Discovers skills on disk and serves metadata cheaply, bodies on demand."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def discover(self, root: Path, *, replace: bool = False) -> SkillRegistry:
        """Scan immediate subdirectories of `root` for a `skill.yaml`. Returns self so
        callers can chain layered discovery (packaged -> global -> project). A missing root
        is skipped. With replace=True a later layer overrides an earlier skill of the same
        name (project > global > packaged); otherwise a duplicate raises."""
        root = Path(root)
        if not root.is_dir():
            return self
        for child in sorted(root.iterdir()):
            manifest_path = child / MANIFEST_FILE
            if not manifest_path.is_file():
                continue
            data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest = SkillManifest.model_validate(data)
            if manifest.name in self._skills and not replace:
                raise ValueError(f"duplicate skill name: {manifest.name}")
            self._skills[manifest.name] = Skill(manifest, child / PLAYBOOK_FILE)
        return self

    def list_metadata(self) -> list[SkillManifest]:
        return [s.manifest for s in self._skills.values()]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def load(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            raise KeyError(f"unknown skill: {name}")
        return skill.body()

    def __len__(self) -> int:
        return len(self._skills)
