from __future__ import annotations

from hexharness.providers.types import ToolSpec
from hexharness.tools.base import Tool


class ToolRegistry:
    """Native tools today; MCP-backed tools register through the same interface later."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        if tool.scope_sensitive and not tool.target_field:
            raise ValueError(f"{tool.name} is scope_sensitive but declares no target_field")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.to_spec() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)
