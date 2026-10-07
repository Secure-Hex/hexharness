from __future__ import annotations

from pathlib import Path

from hexharness.control.secrets import CallbackSecretRequester, DenySecretRequester
from hexharness.control.vault import Vault
from hexharness.skills.engine import SkillRegistry
from hexharness.skills.tool import SkillLookupTool
from hexharness.tools.base import RiskLevel
from hexharness.tools.mcp import FakeMCPClient
from hexharness.tools.native.extend import McpConnectTool, SkillInstallTool
from hexharness.tools.registry import ToolRegistry


async def test_skill_install_inline_then_lookup_loads_body(tmp_path: Path) -> None:
    registry = SkillRegistry()
    tool = SkillInstallTool(registry, tmp_path)

    body = "# Subdomain sweep\n\nEnumerate subdomains, then resolve each.\n"
    out = await tool.run(
        {
            "scope": "project",
            "name": "subdomain_sweep",
            "description": "Enumerate and resolve subdomains.",
            "phase": "recon",
            "playbook_markdown": body,
        }
    )
    assert "subdomain_sweep" in out

    # Dir + files created on disk.
    skill_dir = tmp_path / "subdomain_sweep"
    assert (skill_dir / "skill.yaml").is_file()
    assert (skill_dir / "playbook.md").is_file()

    # Live registry now lists it, and SkillLookupTool over the SAME registry loads its body.
    assert "subdomain_sweep" in [m.name for m in registry.list_metadata()]
    lookup = SkillLookupTool(registry)
    loaded = await lookup.run({"skill_name": "subdomain_sweep"})
    assert loaded == body


async def test_skill_install_scope_routes_to_right_dir(tmp_path: Path) -> None:
    registry = SkillRegistry()
    gdir, pdir = tmp_path / "global", tmp_path / "project"
    tool = SkillInstallTool(registry, tmp_path / "pkg", global_dir=gdir, project_dir=pdir)
    base = {"description": "d", "phase": "recon", "playbook_markdown": "body"}
    await tool.run({**base, "scope": "global", "name": "g_skill"})
    await tool.run({**base, "scope": "project", "name": "p_skill"})
    assert (gdir / "g_skill" / "skill.yaml").is_file()
    assert (pdir / "p_skill" / "skill.yaml").is_file()
    # a bad scope is rejected before any write
    import pytest
    with pytest.raises(Exception):
        await tool.run({**base, "scope": "system", "name": "x"})


async def test_skill_install_registers_existing_dir(tmp_path: Path) -> None:
    src = tmp_path / "canned"
    src.mkdir()
    (src / "skill.yaml").write_text("name: canned\ndescription: d\nphase: webapp\n", encoding="utf-8")
    (src / "playbook.md").write_text("canned body", encoding="utf-8")

    registry = SkillRegistry()
    # library_dir unused in this mode; point it anywhere.
    tool = SkillInstallTool(registry, tmp_path / "library")
    out = await tool.run({"scope": "project", "source_path": str(src)})

    assert "canned" in out
    assert registry.load("canned") == "canned body"


async def test_mcp_connect_registers_tools_and_resolves_secret(tmp_path: Path) -> None:
    registry = ToolRegistry()
    vault = Vault()
    secret_value = "sk-shodan-super-secret"
    requester = CallbackSecretRequester(lambda *, name, reason: secret_value)

    fake = FakeMCPClient()
    tool = McpConnectTool(
        registry,
        vault,
        requester,
        client_factory=lambda command, args: fake,
    )

    out = await tool.run(
        {"command": "shodan-mcp", "args": [], "secret_env": ["SHODAN_API_KEY"]}
    )

    # Remote tools joined the live registry at the conservative default posture.
    assert registry.get("http_get") is not None
    assert registry.get("echo") is not None
    assert registry.get("http_get").risk_level == RiskLevel.INTRUSIVE
    assert registry.get("http_get").requires_approval is True

    # Secret landed in the vault, by name.
    assert vault.has("SHODAN_API_KEY")
    assert vault.get("SHODAN_API_KEY") == secret_value

    # The secret VALUE must appear nowhere in the result string.
    assert secret_value not in out
    assert "SHODAN_API_KEY" in out
    assert "http_get" in out

    # Connected servers are tracked for a future UI.
    assert tool.connected() == ["shodan-mcp"]


async def test_mcp_connect_cancel_aborts_without_connecting() -> None:
    registry = ToolRegistry()
    vault = Vault()

    created: list[FakeMCPClient] = []

    def factory(command: str, args: list[str]) -> FakeMCPClient:
        c = FakeMCPClient()
        created.append(c)
        return c

    tool = McpConnectTool(registry, vault, DenySecretRequester(), client_factory=factory)
    out = await tool.run(
        {"command": "shodan-mcp", "args": [], "secret_env": ["SHODAN_API_KEY"]}
    )

    assert "aborted" in out.lower()
    assert len(registry) == 0          # no tools registered
    assert not vault.has("SHODAN_API_KEY")  # secret never stored
    assert created == []               # client never even built
    assert tool.connected() == []
