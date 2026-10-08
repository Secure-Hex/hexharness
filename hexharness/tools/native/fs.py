"""Filesystem tools, confined to a single workspace root.

Both tools take the engagement workspace in their constructor and route every path
through `_resolve_in_workspace`, the one chokepoint that rejects escapes: `..`
traversal, absolute paths outside the root, and symlinks that point out (Path.resolve()
follows links, so a link to the host filesystem resolves outside and is refused).

- FileReadTool: ACTIVE, no approval — reading a confined file is benign.
- FileWriteTool: INTRUSIVE + requires_approval — writing to disk can plant/clobber.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class _WorkspaceConfined:
    """Shared confinement. The single place path trust is decided."""

    def __init__(self, workspace: str | Path):
        # ponytail: resolve the root once; every request is checked against it.
        self.workspace = Path(workspace).resolve()

    def _resolve_in_workspace(self, path: str) -> Path:
        candidate = (self.workspace / path).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise ValueError(f"path escapes workspace: {path!r}")
        return candidate


class FileReadInput(BaseModel):
    path: str = Field(description="Path relative to the engagement workspace")
    max_bytes: int = Field(default=200_000, description="Truncate the file at this many bytes")


class FileReadTool(_WorkspaceConfined, Tool):
    name = "file_read"
    description = "Read a text file from the engagement workspace."
    input_model = FileReadInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        target = self._resolve_in_workspace(tool_input["path"])
        max_bytes = tool_input.get("max_bytes", 200_000)
        raw = target.read_bytes()
        # Don't dump binary (images, ELF, archives): a NUL byte or lots of non-text bytes
        # would spray control characters and corrupt the terminal. Summarize instead.
        sample = raw[:4096]
        nontext = sum(b < 9 or (13 < b < 32) for b in sample)
        if b"\x00" in sample or (sample and nontext / len(sample) > 0.15):
            return (f"{tool_input['path']}: binary file ({len(raw)} bytes) — not dumping. "
                    "Use exec_command (e.g. `file`, `xxd`, `strings`) for binaries, or the "
                    "browser/screenshot tools for images.")
        return raw[:max_bytes].decode(errors="replace")


class FileWriteInput(BaseModel):
    path: str = Field(description="Path relative to the engagement workspace")
    content: str = Field(description="Text content to write (overwrites any existing file)")


class FileWriteTool(_WorkspaceConfined, Tool):
    name = "file_write"
    description = "Write/overwrite a text file in the engagement workspace. Intrusive — requires approval."
    input_model = FileWriteInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = False
    requires_approval = True

    async def run(self, tool_input: dict) -> str:
        target = self._resolve_in_workspace(tool_input["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tool_input["content"])
        return f"wrote {len(tool_input['content'])} chars to {target.relative_to(self.workspace)}"
