"""Static binary-analysis / reversing tools, confined to a single workspace root.

These tools NEVER execute the target. They only parse it with standard binutils
(`file`, `strings`, `objdump -d`, `readelf`), which read the file without running
its code, so they run as HOST subprocesses (not the Docker sandbox) and are confined
to the engagement workspace exactly like fs.py.

- BinaryInfoTool: `file` + `strings` summary.
- ChecksecTool: RELRO/NX/PIE/Canary from `readelf -a`.
- DisassembleTool: first N lines of `objdump -d`.

All three are ACTIVE (reading/analysis), not scope-sensitive (a local file is not a
network target), and need no approval. The command runner is injectable for testing;
the default shells out to the real binutils via subprocess (argv as a LIST, no shell).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

# runner(argv) -> (exit_code, stdout, stderr)
Runner = Callable[[list[str]], "tuple[int, str, str]"]

# ponytail: 127 is the shell convention for "command not found"; we reuse it so a
# missing binutils binary turns into a clear message instead of a stack trace.
_NOT_FOUND = 127


def _default_runner(argv: list[str], *, timeout: float = 60.0) -> tuple[int, str, str]:
    """Run a binutils command as a host subprocess. argv is a LIST — never a shell string."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return (_NOT_FOUND, "", f"{argv[0]!r}: binary not found (install binutils)")
    except subprocess.TimeoutExpired:
        return (124, "", f"{argv[0]!r}: timed out after {timeout}s")
    return (p.returncode, p.stdout, p.stderr)


class _BinaryToolBase(Tool):
    """Shared workspace confinement + injectable runner for the binary tools.

    Confinement mirrors fs.py's `_resolve_in_workspace` chokepoint (reimplemented here,
    not imported, to keep the guard local and the trust boundary obvious).
    """

    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = False

    def __init__(self, workspace: str | Path, runner: Runner | None = None):
        # ponytail: resolve the root once; every request is checked against it.
        self.workspace = Path(workspace).resolve()
        self._runner: Runner = runner or _default_runner

    def _resolve_in_workspace(self, path: str) -> Path:
        candidate = (self.workspace / path).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise ValueError(f"path escapes workspace: {path!r}")
        return candidate

    def _run(self, argv: list[str]) -> tuple[int, str, str] | str:
        """Run a command. Returns an error string if the binary is missing, else the tuple."""
        code, out, err = self._runner(argv)
        if code == _NOT_FOUND:
            return f"error: {err or argv[0] + ': command not found'}"
        return (code, out, err)


class BinaryInfoInput(BaseModel):
    path: str = Field(description="Path to the binary, relative to the engagement workspace")
    max_strings: int = Field(default=200, description="Cap the number of extracted strings")


class BinaryInfoTool(_BinaryToolBase):
    name = "binary_info"
    description = (
        "Statically identify a binary in the workspace: file type (via `file`) plus notable "
        "ASCII strings (via `strings -n 8`). Does not execute the target."
    )
    input_model = BinaryInfoInput

    async def run(self, tool_input: dict) -> str:
        target = self._resolve_in_workspace(tool_input["path"])
        max_strings = int(tool_input.get("max_strings", 200))

        file_res = self._run(["file", str(target)])
        if isinstance(file_res, str):
            return file_res
        _, file_out, _ = file_res

        strings_res = self._run(["strings", "-n", "8", str(target)])
        if isinstance(strings_res, str):
            return strings_res
        _, strings_out, _ = strings_res

        lines = [s for s in strings_out.splitlines() if s.strip()]
        shown = lines[:max_strings]
        more = len(lines) - len(shown)

        parts = [f"File type: {file_out.strip()}", "", f"Strings ({len(shown)} shown):"]
        parts.extend(shown)
        if more > 0:
            parts.append(f"... ({more} more strings truncated)")
        return "\n".join(parts)


class ChecksecInput(BaseModel):
    path: str = Field(description="Path to the ELF binary, relative to the engagement workspace")


class ChecksecTool(_BinaryToolBase):
    name = "checksec"
    description = (
        "Report binary hardening (RELRO / NX / PIE / Stack Canary) for an ELF in the workspace, "
        "parsed from `readelf -a`. Heuristic — does not execute the target."
    )
    input_model = ChecksecInput

    async def run(self, tool_input: dict) -> str:
        # ponytail: readelf-based heuristic. For ground truth use pwntools `checksec`
        # (reads the full ELF model) — this covers the common cases without the dep.
        target = self._resolve_in_workspace(tool_input["path"])

        res = self._run(["readelf", "-a", str(target)])
        if isinstance(res, str):
            return res
        _, out, err = res
        if not out:
            return f"error: readelf produced no output ({err.strip() or 'not an ELF?'})"

        return "\n".join(
            f"{k}: {v}" for k, v in self._parse_checksec(out).items()
        )

    @staticmethod
    def _parse_checksec(text: str) -> dict[str, str]:
        # NX: non-executable stack. GNU_STACK with RWE => executable stack (NX disabled).
        if "GNU_STACK" in text:
            # The flags sit at the end of the GNU_STACK program-header line.
            stack_line = next((l for l in text.splitlines() if "GNU_STACK" in l), "")
            nx = "Disabled" if "RWE" in stack_line else "Enabled"
        else:
            nx = "Unknown (no GNU_STACK)"

        # PIE: position-independent executable => ELF type DYN (shared-object-style).
        if "Type:" in text:
            type_line = next((l for l in text.splitlines() if l.strip().startswith("Type:")), "")
            pie = "Enabled" if "DYN" in type_line else "No"
        else:
            pie = "Unknown"

        # RELRO: GNU_RELRO segment => at least partial; BIND_NOW => full.
        if "GNU_RELRO" in text:
            relro = "Full" if "BIND_NOW" in text else "Partial"
        else:
            relro = "No"

        # Canary: presence of the stack-check symbol.
        canary = "Found" if "__stack_chk_fail" in text else "Not found"

        return {"RELRO": relro, "NX": nx, "PIE": pie, "Canary": canary}


class DisassembleInput(BaseModel):
    path: str = Field(description="Path to the binary, relative to the engagement workspace")
    section: str = Field(default="", description="Optional section to disassemble (objdump -j), e.g. .text")
    max_lines: int = Field(default=200, description="Truncate disassembly to this many lines")


class DisassembleTool(_BinaryToolBase):
    name = "disassemble"
    description = (
        "Disassemble a binary in the workspace with `objdump -d` (optionally one section), "
        "truncated to max_lines. Does not execute the target."
    )
    input_model = DisassembleInput

    async def run(self, tool_input: dict) -> str:
        target = self._resolve_in_workspace(tool_input["path"])
        section = str(tool_input.get("section", "") or "")
        max_lines = int(tool_input.get("max_lines", 200))

        argv = ["objdump", "-d"]
        if section:
            argv += ["-j", section]
        argv.append(str(target))

        res = self._run(argv)
        if isinstance(res, str):
            return res
        code, out, err = res
        if not out:
            return f"error: objdump produced no output ({err.strip() or f'exit {code}'})"

        lines = out.splitlines()
        shown = lines[:max_lines]
        if len(lines) > max_lines:
            shown.append(f"... ({len(lines) - max_lines} more lines truncated)")
        return "\n".join(shown)
