"""Self-extension tools: let the MODEL, by chatting, grow its own capabilities at
runtime. Two tools, both hard-gated by the control plane (requires_approval=True):

  - SkillInstallTool  — write/register a skill into the LIVE SkillRegistry so the
                        existing SkillLookupTool sees it next turn.
  - McpConnectTool    — spawn/connect an MCP server and fold its remote tools into
                        the LIVE ToolRegistry, through the same control plane as
                        native tools.

Neither bypasses authorization: the model proposes, the control plane disposes. The
model never sees risk fields; approval and secret acquisition happen out-of-band.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field, model_validator

from hexharness.control.secrets import SecretRequester
from hexharness.control.vault import Vault
from hexharness.skills.engine import (
    MANIFEST_FILE,
    PLAYBOOK_FILE,
    Skill,
    SkillManifest,
    SkillRegistry,
)
from hexharness.tools.base import RiskLevel, Tool
from hexharness.tools.mcp import (
    Classification,
    MCPClient,
    StdioMCPClient,
    register_mcp_tools,
)
from hexharness.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- skills


class SkillInstallInput(BaseModel):
    """Two modes: author a new skill inline, OR register an existing on-disk dir."""

    # Where to install. REQUIRED so you must ASK the operator first: "project" = only this
    # engagement; "global" = ~/.hexharness/skills, available to every future engagement.
    scope: str = Field(
        description="Install scope: 'project' (this engagement only) or 'global' (all "
        "engagements). ASK THE OPERATOR which they want before installing."
    )
    # Inline authoring mode.
    name: str | None = Field(default=None, description="New skill's unique name.")
    description: str | None = Field(default=None, description="One-line summary.")
    phase: str | None = Field(default=None, description="Engagement phase, e.g. 'recon'.")
    playbook_markdown: str | None = Field(default=None, description="Full playbook body (markdown).")
    # Registration mode.
    source_path: str | None = Field(
        default=None, description="Path to an existing skill directory (holds skill.yaml + playbook.md)."
    )

    @model_validator(mode="after")
    def _one_mode(self) -> SkillInstallInput:
        if self.scope not in ("project", "global"):
            raise ValueError("scope must be 'project' or 'global'")
        if self.source_path:
            return self
        missing = [f for f in ("name", "description", "phase", "playbook_markdown") if not getattr(self, f)]
        if missing:
            raise ValueError(
                "provide source_path, OR all of name/description/phase/playbook_markdown; "
                f"missing: {', '.join(missing)}"
            )
        return self


def _install_skill_dir(registry: SkillRegistry, skill_dir: Path) -> SkillManifest:
    """Parse a skill dir's manifest and insert it into the LIVE registry.

    # ponytail: writes registry._skills directly. SkillRegistry.discover() raises on any
    # already-known name, so it cannot be re-run over the whole library to pick up one new
    # skill — and the registry exposes no public insert. One dict write is the smallest safe
    # re-discovery; upgrade path is a public SkillRegistry.add() when there's a second caller.
    """
    data = yaml.safe_load((skill_dir / MANIFEST_FILE).read_text(encoding="utf-8")) or {}
    manifest = SkillManifest.model_validate(data)
    registry._skills[manifest.name] = Skill(manifest, skill_dir / PLAYBOOK_FILE)
    return manifest


class SkillInstallTool(Tool):
    name = "skill_install"
    description = (
        "Install a new skill so it becomes browsable/loadable via skill_lookup. Either author "
        "one inline (name, description, phase, playbook_markdown) or register an existing on-disk "
        "skill directory (source_path). ALWAYS ask the operator whether to install for this "
        "project only or globally, then pass scope='project' or scope='global'."
    )
    input_model = SkillInstallInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(self, skill_registry: SkillRegistry, library_dir: Path, *,
                 global_dir: Path | None = None, project_dir: Path | None = None) -> None:
        self._registry = skill_registry
        self._library_dir = Path(library_dir)  # fallback target when a scope dir is unset
        self._global_dir = Path(global_dir) if global_dir else None
        self._project_dir = Path(project_dir) if project_dir else None

    def _target_dir(self, scope: str) -> Path:
        chosen = self._global_dir if scope == "global" else self._project_dir
        return chosen or self._library_dir  # fall back (e.g. in tests) when unset

    async def run(self, tool_input: dict) -> str:
        data = self.input_model.model_validate(tool_input)

        if data.source_path:
            skill_dir = Path(data.source_path)
            if not (skill_dir / MANIFEST_FILE).is_file():
                return f"no {MANIFEST_FILE} found in {skill_dir}"
            manifest = _install_skill_dir(self._registry, skill_dir)
            return f"registered skill '{manifest.name}' ({manifest.phase}) from {skill_dir}"

        # Inline authoring: create <scope dir>/<name>/ with skill.yaml + playbook.md.
        skill_dir = self._target_dir(data.scope) / data.name  # type: ignore[arg-type]
        skill_dir.mkdir(parents=True, exist_ok=True)
        manifest_yaml = yaml.safe_dump(
            {"name": data.name, "description": data.description, "phase": data.phase},
            sort_keys=False,
        )
        (skill_dir / MANIFEST_FILE).write_text(manifest_yaml, encoding="utf-8")
        (skill_dir / PLAYBOOK_FILE).write_text(data.playbook_markdown or "", encoding="utf-8")
        manifest = _install_skill_dir(self._registry, skill_dir)
        return f"installed skill '{manifest.name}' ({manifest.phase}, {data.scope}) at {skill_dir}"


# ------------------------------------------------------------------------------ mcp


class McpConnectInput(BaseModel):
    command: str = Field(description="Executable that speaks MCP over stdio.")
    args: list[str] = Field(default_factory=list, description="Arguments for the command.")
    secret_env: list[str] = Field(
        default_factory=list,
        description="Names of secrets the server needs; acquired out-of-band, never echoed.",
    )
    classify: dict | None = Field(
        default=None,
        description="Optional per-tool risk override: {tool_name: [risk, scope_sensitive, "
        "requires_approval, target_field]}. Omit to use the safe INTRUSIVE+approval default.",
    )


def _make_classify(mapping: dict | None) -> Callable[[str], Classification | None] | None:
    if not mapping:
        return None

    def classify(name: str) -> Classification | None:
        entry = mapping.get(name)
        if entry is None:
            return None
        risk, scope_sensitive, requires_approval, target_field = entry
        return (RiskLevel(risk), bool(scope_sensitive), bool(requires_approval), target_field)

    return classify


class McpConnectTool(Tool):
    name = "mcp_connect"
    description = (
        "Connect to an MCP server (stdio command + args) and add its remote tools to the live "
        "toolset. Any secrets the server needs are named in secret_env and acquired out-of-band."
    )
    input_model = McpConnectInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = False
    requires_approval = True

    def __init__(
        self,
        registry: ToolRegistry,
        vault: Vault,
        secret_requester: SecretRequester,
        *,
        client_factory: Callable[[str, list[str]], MCPClient] | None = None,
    ) -> None:
        self._registry = registry
        self._vault = vault
        self._secrets = secret_requester
        self._client_factory = client_factory or (lambda command, args: StdioMCPClient(command, args))
        # ponytail: keep references so a future UI can list + close live servers.
        self._clients: list[tuple[str, MCPClient]] = []

    def connected(self) -> list[str]:
        """Server commands currently connected (for a future management UI)."""
        return [command for command, _ in self._clients]

    async def run(self, tool_input: dict) -> str:
        data = self.input_model.model_validate(tool_input)

        # Dynamic, per-invocation secret path: fill any secret_env the vault lacks. Fail-closed.
        for secret_name in data.secret_env:
            if self._vault.has(secret_name):
                continue
            value = await self._secrets.request(
                name=secret_name, reason=f"MCP server '{data.command}' requires it"
            )
            if value is None:
                # Operator cancelled — abort BEFORE connecting. Never leak the name's value.
                return f"aborted: secret '{secret_name}' was not provided; did not connect to {data.command}"
            self._vault.set(secret_name, value)

        client = self._client_factory(data.command, data.args)
        connect = getattr(client, "connect", None)
        if connect is not None:
            await connect()
        self._clients.append((data.command, client))

        wrapped = await register_mcp_tools(
            self._registry, client, classify=_make_classify(data.classify)
        )
        names = [t.name for t in wrapped]
        # Acknowledge secrets by NAME only — values never appear here.
        resolved = ", ".join(data.secret_env) if data.secret_env else "none"
        return (
            f"connected to MCP server '{data.command}'; registered {len(names)} tool(s): "
            f"{', '.join(names) or '(none)'}. Secrets resolved: {resolved}."
        )
