from __future__ import annotations

import pytest

from hexharness.tools.native.binary import (
    BinaryInfoTool,
    ChecksecTool,
    DisassembleTool,
)


class _FakeRunner:
    """Records argv and replays canned output keyed by the binutils program name.

    Canned values are (exit_code, stdout, stderr). Lets us assert the argv the tool
    built (incl. the resolved in-workspace path) without needing a real binary.
    """

    def __init__(self, canned: dict[str, tuple[int, str, str]]):
        self.canned = canned
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        return self.canned.get(argv[0], (0, "", ""))


# Canned readelf -a text with every protection ON.
_HARDENED_READELF = """
ELF Header:
  Type:                              DYN (Shared object file)
Program Headers:
  Type           Offset   VirtAddr           Flags Align
  GNU_STACK      0x000000 0x0000000000000000 RW  0x10
  GNU_RELRO      0x002d80 0x0000000000003d80 R   0x1
Dynamic section at offset 0x2d90:
  0x000000000000001e (FLAGS)              BIND_NOW
Symbol table '.dynsym' contains 7 entries:
     3: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND __stack_chk_fail@GLIBC_2.4 (3)
"""

# Canned readelf -a text with every protection OFF.
_WEAK_READELF = """
ELF Header:
  Type:                              EXEC (Executable file)
Program Headers:
  Type           Offset   VirtAddr           Flags Align
  GNU_STACK      0x000000 0x0000000000000000 RWE 0x10
Symbol table '.dynsym' contains 4 entries:
     1: 0000000000000000     0 FUNC    GLOBAL DEFAULT  UND printf@GLIBC_2.2.5 (2)
"""


async def test_binary_info_builds_argv_and_summarizes(tmp_path):
    (tmp_path / "sample.bin").write_bytes(b"\x7fELF")
    runner = _FakeRunner({
        "file": (0, "sample.bin: ELF 64-bit LSB pie executable, x86-64", ""),
        "strings": (0, "shrt\n/bin/sh\nGLIBC_2.2.5\nflag{notable}\n", ""),
    })
    out = await BinaryInfoTool(tmp_path, runner).run({"path": "sample.bin"})

    resolved = str((tmp_path / "sample.bin").resolve())
    assert runner.calls[0] == ["file", resolved]
    assert runner.calls[1] == ["strings", "-n", "8", resolved]
    assert "ELF 64-bit" in out
    assert "/bin/sh" in out
    assert "flag{notable}" in out


async def test_binary_info_caps_strings(tmp_path):
    (tmp_path / "s.bin").write_bytes(b"x")
    many = "\n".join(f"stringno{i:04d}" for i in range(500))
    runner = _FakeRunner({"file": (0, "data", ""), "strings": (0, many, "")})
    out = await BinaryInfoTool(tmp_path, runner).run({"path": "s.bin", "max_strings": 10})
    assert "Strings (10 shown)" in out
    assert "490 more strings truncated" in out


async def test_checksec_detects_all_protections(tmp_path):
    (tmp_path / "hard.bin").write_bytes(b"x")
    runner = _FakeRunner({"readelf": (0, _HARDENED_READELF, "")})
    out = await ChecksecTool(tmp_path, runner).run({"path": "hard.bin"})

    assert runner.calls[0] == ["readelf", "-a", str((tmp_path / "hard.bin").resolve())]
    assert "RELRO: Full" in out
    assert "NX: Enabled" in out
    assert "PIE: Enabled" in out
    assert "Canary: Found" in out


async def test_checksec_detects_missing_protections(tmp_path):
    (tmp_path / "weak.bin").write_bytes(b"x")
    runner = _FakeRunner({"readelf": (0, _WEAK_READELF, "")})
    out = await ChecksecTool(tmp_path, runner).run({"path": "weak.bin"})
    assert "RELRO: No" in out
    assert "NX: Disabled" in out
    assert "PIE: No" in out
    assert "Canary: Not found" in out


async def test_disassemble_truncates(tmp_path):
    (tmp_path / "d.bin").write_bytes(b"x")
    disasm = "\n".join(f"  {i}: nop" for i in range(300))
    runner = _FakeRunner({"objdump": (0, disasm, "")})
    out = await DisassembleTool(tmp_path, runner).run(
        {"path": "d.bin", "section": ".text", "max_lines": 50}
    )
    assert runner.calls[0] == ["objdump", "-d", "-j", ".text", str((tmp_path / "d.bin").resolve())]
    assert out.count("\n") == 50  # 50 lines + truncation notice
    assert "250 more lines truncated" in out


async def test_disassemble_no_section_omits_j_flag(tmp_path):
    (tmp_path / "d.bin").write_bytes(b"x")
    runner = _FakeRunner({"objdump": (0, "main:\n  push rbp", "")})
    await DisassembleTool(tmp_path, runner).run({"path": "d.bin"})
    assert "-j" not in runner.calls[0]


async def test_missing_binary_returns_clear_message(tmp_path):
    (tmp_path / "x.bin").write_bytes(b"x")
    runner = _FakeRunner({"file": (127, "", "'file': binary not found")})
    out = await BinaryInfoTool(tmp_path, runner).run({"path": "x.bin"})
    assert out.startswith("error:")
    assert "not found" in out


@pytest.mark.parametrize(
    "tool_cls", [BinaryInfoTool, ChecksecTool, DisassembleTool]
)
async def test_path_escape_refused_without_invoking_runner(tmp_path, tool_cls):
    runner = _FakeRunner({})
    tool = tool_cls(tmp_path, runner)
    with pytest.raises(ValueError):
        await tool.run({"path": "../../etc/passwd"})
    assert runner.calls == []  # guard fires before any subprocess


def test_risk_and_scope_fields(tmp_path):
    from hexharness.tools.base import RiskLevel

    for tool in (BinaryInfoTool(tmp_path), ChecksecTool(tmp_path), DisassembleTool(tmp_path)):
        assert tool.risk_level is RiskLevel.ACTIVE
        assert tool.scope_sensitive is False
        assert tool.requires_approval is False
