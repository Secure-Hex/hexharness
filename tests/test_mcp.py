"""MCP tool integration — uses FakeMCPClient, never the real `mcp` SDK or a subprocess."""
from __future__ import annotations

from hexharness.tools.base import RiskLevel
from hexharness.tools.mcp import FakeMCPClient, MCPTool, register_mcp_tools
from hexharness.tools.registry import ToolRegistry


async def test_register_wraps_and_registers_remote_tools():
    registry = ToolRegistry()
    wrapped = await register_mcp_tools(registry, FakeMCPClient())

    assert len(registry) == 2
    assert {t.name for t in wrapped} == {"http_get", "echo"}
    http = registry.get("http_get")
    assert isinstance(http, MCPTool)
    assert "url" in http.input_model.model_json_schema()["properties"]


async def test_unclassified_defaults_to_intrusive_and_approval():
    registry = ToolRegistry()
    await register_mcp_tools(registry, FakeMCPClient())

    http = registry.get("http_get")
    assert http.risk_level is RiskLevel.INTRUSIVE
    assert http.requires_approval is True
    assert http.scope_sensitive is False


async def test_classify_override_can_mark_passive():
    registry = ToolRegistry()

    def classify(name: str):
        if name == "echo":
            return (RiskLevel.PASSIVE, False, False, None)
        return None  # http_get keeps the conservative default

    await register_mcp_tools(registry, FakeMCPClient(), classify=classify)

    echo = registry.get("echo")
    assert echo.risk_level is RiskLevel.PASSIVE
    assert echo.requires_approval is False
    # unclassified one stays conservative
    assert registry.get("http_get").risk_level is RiskLevel.INTRUSIVE


async def test_classify_scope_sensitive_requires_target_field():
    """Registry rejects a scope_sensitive tool with no target_field — the override must
    supply one, proving the MCP wrapper honours the same control-plane invariant."""
    registry = ToolRegistry()

    def classify(name: str):
        if name == "http_get":
            return (RiskLevel.ACTIVE, True, True, "url")
        return None

    await register_mcp_tools(registry, FakeMCPClient(), classify=classify)
    http = registry.get("http_get")
    assert http.scope_sensitive is True
    assert http.extract_target({"url": "http://t"}) == "http://t"


async def test_run_delegates_to_call_tool():
    client = FakeMCPClient()
    registry = ToolRegistry()
    await register_mcp_tools(registry, client)

    out = await registry.get("echo").run({"message": "hi"})
    assert out == "echo called with {'message': 'hi'}"
    assert client.calls == [("echo", {"message": "hi"})]
