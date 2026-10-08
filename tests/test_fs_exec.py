from __future__ import annotations

import shutil

import pytest

from hexharness.sandbox.executor import SandboxResult
from hexharness.tools.native.exec import ExecCommandTool
from hexharness.tools.native.fs import FileReadTool, FileWriteTool


async def test_write_then_read_roundtrip(tmp_path):
    writer = FileWriteTool(tmp_path)
    reader = FileReadTool(tmp_path)
    await writer.run({"path": "sub/note.txt", "content": "hello hex"})
    assert (tmp_path / "sub" / "note.txt").read_text() == "hello hex"
    assert await reader.run({"path": "sub/note.txt"}) == "hello hex"


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd", "sub/../../outside.txt"])
async def test_read_refuses_escape(tmp_path, bad):
    with pytest.raises(ValueError):
        await FileReadTool(tmp_path).run({"path": bad})


@pytest.mark.parametrize("bad", ["../outside.txt", "/tmp/outside.txt"])
async def test_write_refuses_escape_and_does_not_touch_file(tmp_path, bad):
    outside = tmp_path.parent / "outside.txt"
    assert not outside.exists()
    with pytest.raises(ValueError):
        await FileWriteTool(tmp_path).run({"path": bad, "content": "x"})
    assert not outside.exists()


class _FakeExecutor:
    """Records the exact call so we can assert argv stays a list (no shell string)."""

    def __init__(self):
        self.calls = []

    async def exec_in_session(self, image, argv, *, timeout=None, workspace=None, hardware=False):
        self.calls.append((image, argv, timeout, workspace))
        return SandboxResult(0, "fake-out", "")


async def test_exec_forwards_argv_as_list():
    fake = _FakeExecutor()
    tool = ExecCommandTool(fake, image="alpine:3.20", workspace="/ws")
    out = await tool.run({"argv": ["echo", "hi; rm -rf /"], "timeout": 5})
    image, argv, timeout, workspace = fake.calls[0]
    assert argv == ["echo", "hi; rm -rf /"]  # passed through intact, never joined
    assert isinstance(argv, list)
    assert (image, timeout, workspace) == ("alpine:3.20", 5, "/ws")
    assert out == "fake-out"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
async def test_exec_real_docker():
    out = await ExecCommandTool().run({"argv": ["echo", "ponytail"]})
    assert "ponytail" in out
