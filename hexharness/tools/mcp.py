"""MCP-backed tools. MCP is the harness's PRIMARY tool protocol, so a tool discovered
from an MCP server is wrapped as a first-class `Tool` and registered through the SAME
`ToolRegistry` — it flows through the identical control plane (scope, ROE, budget) as a
native tool. The control plane cannot tell an MCP tool from a native one.

Risk policy: MCP does not declare pentest risk, so we classify CONSERVATIVELY — default
every remote tool to INTRUSIVE + requires_approval unless an explicit override says
otherwise. A permissive, locked-down posture is the safe default for third-party tools.

The `mcp` SDK is lazy-imported (optional dep `[mcp]`) so this module imports without it —
tests use FakeMCPClient and never touch the SDK or a subprocess.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, create_model

from hexharness.tools.base import RiskLevel, Tool

# A classify callback maps a remote tool name to its risk posture, or returns None to
# accept the conservative default. The tuple is (risk_level, scope_sensitive,
# requires_approval, target_field).
Classification = tuple[RiskLevel, bool, bool, "str | None"]
Classify = Callable[[str], "Classification | None"]


@runtime_checkable
class MCPClient(Protocol):
    """Thin transport-agnostic interface to one MCP server."""

    async def list_tools(self) -> list[dict]:
        """Each dict: {name, description, inputSchema}."""
        ...

    async def call_tool(self, name: str, arguments: dict) -> str:
        ...


_JSON_TO_PY: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_input_model(tool_name: str, input_schema: dict) -> type[BaseModel]:
    """Build a permissive pydantic model from an MCP JSON inputSchema. Fields are loosely
    typed and all optional (the MCP server does the authoritative validation); extra keys
    are allowed so nothing is dropped. The model exists mainly to carry a json schema to
    the provider and to normalise input."""
    props = (input_schema or {}).get("properties", {})
    fields: dict[str, Any] = {}
    for fname, fschema in props.items():
        py = _JSON_TO_PY.get((fschema or {}).get("type", ""), Any)
        # ponytail: all-optional. MCP server validates required-ness authoritatively.
        fields[fname] = (py | None, None)
    model = create_model(  # type: ignore[call-overload]
        f"MCP_{tool_name}_Input",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )
    return model


class MCPTool(Tool):
    """Wraps one remote MCP tool as a first-class Tool. Attributes are set per-instance
    (not class-level) because each wraps a different remote tool."""

    def __init__(
        self,
        client: MCPClient,
        spec: dict,
        *,
        risk_level: RiskLevel,
        scope_sensitive: bool,
        requires_approval: bool,
        target_field: str | None,
    ) -> None:
        self._client = client
        self._remote_name = spec["name"]
        self.name = spec["name"]
        self.description = spec.get("description", "") or f"MCP tool {spec['name']}"
        self.input_model = _build_input_model(spec["name"], spec.get("inputSchema", {}))
        self.risk_level = risk_level
        self.scope_sensitive = scope_sensitive
        self.requires_approval = requires_approval
        self.target_field = target_field

    async def run(self, tool_input: dict) -> str:
        return await self._client.call_tool(self._remote_name, tool_input)


# Conservative default for an unclassified remote tool: treat as dangerous and gate it.
_DEFAULT: Classification = (RiskLevel.INTRUSIVE, False, True, None)


async def register_mcp_tools(
    registry: Any,
    client: MCPClient,
    *,
    classify: Classify | None = None,
) -> list[MCPTool]:
    """List remote tools, wrap each as an MCPTool, and register them. Returns the wrappers."""
    wrapped: list[MCPTool] = []
    for spec in await client.list_tools():
        risk, scope_sensitive, requires_approval, target_field = _DEFAULT
        if classify is not None:
            override = classify(spec["name"])
            if override is not None:
                risk, scope_sensitive, requires_approval, target_field = override
        tool = MCPTool(
            client,
            spec,
            risk_level=risk,
            scope_sensitive=scope_sensitive,
            requires_approval=requires_approval,
            target_field=target_field,
        )
        registry.register(tool)  # registry enforces target_field when scope_sensitive
        wrapped.append(tool)
    return wrapped


class StdioMCPClient:
    """MCPClient over the `mcp` SDK stdio transport. Spawns the server as a subprocess.
    The SDK is lazy-imported so this module (and the harness) imports without `mcp`
    installed — `mcp` lives in optional-deps `[mcp]`."""

    def __init__(self, command: str, args: list[str] | None = None, env: dict | None = None) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._session: Any = None
        self._stack: Any = None

    async def connect(self) -> None:
        # ponytail: lazy import — keeps `mcp` optional and tests SDK-free.
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters  # type: ignore
        from mcp.client.stdio import stdio_client  # type: ignore

        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            await self.connect()
        result = await self._session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema or {}}
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self._session is None:
            await self.connect()
        result = await self._session.call_tool(name, arguments)
        # MCP returns a list of content parts; join the text parts into a string.
        parts = [getattr(c, "text", "") for c in (result.content or [])]
        return "\n".join(p for p in parts if p)

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None


class FakeMCPClient:
    """In-memory MCPClient for tests — a couple of canned tools, no SDK, no subprocess.
    call_tool echoes the arguments so delegation is observable."""

    def __init__(self, tools: list[dict] | None = None) -> None:
        self.tools = tools if tools is not None else [
            {
                "name": "http_get",
                "description": "Fetch a URL over HTTP.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
            {
                "name": "echo",
                "description": "Echo a message back.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            },
        ]
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[dict]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return f"{name} called with {arguments}"
