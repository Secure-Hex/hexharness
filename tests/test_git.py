from __future__ import annotations

import base64

import pytest

from hexharness.control.vault import Vault
from hexharness.sandbox.executor import SandboxResult
from hexharness.tools.base import RiskLevel
from hexharness.tools.native.git import GitCloneTool, GitRepoTool


class _FakeExecutor:
    def __init__(self, result: SandboxResult | None = None):
        self.calls: list[list[str]] = []
        self.result = result or SandboxResult(0, "out", "")

    async def exec_in_session(self, image, argv, *, timeout=None, workspace=None, hardware=False):
        self.calls.append(argv)
        return self.result


def _git_args(argv: list[str]) -> list[str]:
    """argv after the hardened `git -c ... --no-pager` prefix."""
    return argv[argv.index("--no-pager") + 1:]


async def _run_repo(tool_input: dict) -> list[str]:
    fake = _FakeExecutor()
    await GitRepoTool(fake).run(tool_input)
    return _git_args(fake.calls[0])


def test_risk_posture():
    assert (GitRepoTool.risk_level, GitRepoTool.requires_approval) == (RiskLevel.PASSIVE, False)
    assert (GitCloneTool.risk_level, GitCloneTool.requires_approval) == (RiskLevel.ACTIVE, True)


async def test_hardened_prefix():
    fake = _FakeExecutor()
    await GitRepoTool(fake).run({"action": "status", "repo": "repos/x"})
    argv = fake.calls[0]
    assert argv[:2] == ["env", "GIT_TERMINAL_PROMPT=0"]
    assert "core.hooksPath=/dev/null" in argv and "core.fsmonitor=false" in argv


@pytest.mark.parametrize("tool_input,expected", [
    ({"action": "status"}, ["status", "--short", "--branch"]),
    ({"action": "log", "n": 5, "rev": "main", "path": "src"},
     ["log", "-n5", "--format=%h %ad %an <%ae>%n    %s", "--date=short", "main", "--", "src"]),
    ({"action": "show", "rev": "HEAD~1", "path": "a.txt"}, ["show", "--no-ext-diff", "--no-textconv", "HEAD~1:a.txt"]),
    ({"action": "diff", "rev": "a..b"}, ["diff", "--no-ext-diff", "--no-textconv", "a..b", "--"]),
    ({"action": "grep", "pattern": "-rf", "rev": "HEAD"}, ["grep", "-n", "-I", "-e", "-rf", "HEAD", "--"]),
    ({"action": "ls_files"}, ["ls-files", "--"]),
    ({"action": "ls_files", "rev": "v1"}, ["ls-tree", "-r", "--name-only", "v1", "--"]),
    ({"action": "blame", "path": "--evil"}, ["blame", "--", "--evil"]),
    ({"action": "history_search", "pattern": "--output=/x", "n": 3},
     ["log", "-S--output=/x", "--all", "-p", "--no-ext-diff", "--no-textconv", "-n3",
      "--format=%h %ad %an <%ae>%n    %s", "--date=short", "--"]),
    ({"action": "history_search", "pattern": "AKIA[0-9A-Z]{16}", "regex": True}, None),
])
async def test_repo_argv(tool_input, expected):
    args = await _run_repo({"repo": "repos/x", **tool_input})
    assert args[:2] == ["-C", "/workspace/repos/x"]
    if expected is None:
        assert "-GAKIA[0-9A-Z]{16}" in args
    else:
        assert args[2:] == expected


@pytest.mark.parametrize("repo", ["../etc", "/etc", "repos/../../etc", "/workspace/../root"])
async def test_repo_path_escape_rejected(repo):
    fake = _FakeExecutor()
    with pytest.raises(ValueError):
        await GitRepoTool(fake).run({"action": "status", "repo": repo})
    assert fake.calls == []


async def test_absolute_workspace_path_allowed():
    assert (await _run_repo({"action": "status", "repo": "/workspace/repos/x"}))[:2] == ["-C", "/workspace/repos/x"]


@pytest.mark.parametrize("tool_input", [
    {"action": "log", "rev": "--output=/workspace/pwn"},
    {"action": "diff", "rev": "-p"},
    {"action": "show", "rev": "--ext-diff"},
    {"action": "grep"},  # missing pattern
    {"action": "blame"},  # missing path
])
async def test_repo_option_injection_rejected(tool_input):
    fake = _FakeExecutor()
    with pytest.raises(ValueError):
        await GitRepoTool(fake).run({"repo": "repos/x", **tool_input})
    assert fake.calls == []


async def test_clone_argv_and_default_dest():
    fake = _FakeExecutor()
    out = await GitCloneTool(fake).run({"url": "https://github.com/octocat/Hello-World.git", "ref": "master"})
    assert _git_args(fake.calls[0]) == [
        "clone", "--no-recurse-submodules", "--depth", "1", "--branch", "master",
        "--", "https://github.com/octocat/Hello-World.git", "/workspace/repos/Hello-World"]
    assert out.startswith("cloned into /workspace/repos/Hello-World")


async def test_clone_scp_url_full_depth():
    fake = _FakeExecutor()
    await GitCloneTool(fake).run({"url": "git@gitlab.example:grp/app.git", "depth": 0})
    assert _git_args(fake.calls[0]) == [
        "clone", "--no-recurse-submodules", "--", "git@gitlab.example:grp/app.git", "/workspace/repos/app"]


@pytest.mark.parametrize("tool_input", [
    {"url": "--upload-pack=touch /tmp/pwn"},
    {"url": "ext::sh -c touch% /tmp/pwn"},
    {"url": "file:///etc"},
    {"url": "/etc"},
    {"url": "https://h/r.git", "ref": "--upload-pack=x"},
    {"url": "https://h/r.git", "repo": "../../outside"},
    {"action": "pull", "repo": "/etc"},
])
async def test_clone_rejects_injection(tool_input):
    fake = _FakeExecutor()
    with pytest.raises(ValueError):
        await GitCloneTool(fake).run(tool_input)
    assert fake.calls == []


async def test_clone_token_is_header_scoped_and_redacted():
    vault = Vault()
    vault.set("GITHUB_TOKEN", "ghp_secret123")
    b64 = base64.b64encode(b"x-access-token:ghp_secret123").decode()
    # A git that echoes the secret back must not leak it to the model.
    fake = _FakeExecutor(SandboxResult(128, "", f"fatal: auth ghp_secret123 {b64}"))
    out = await GitCloneTool(fake, vault=vault).run({"url": "https://github.com/acme/private"})
    argv = fake.calls[0]
    assert f"http.https://github.com/.extraHeader=Authorization: Basic {b64}" in argv
    assert "https://github.com/acme/private" in argv  # token never put in the URL
    assert "ghp_secret123" not in out and b64 not in out
    assert out.startswith("exit 128")


async def test_clone_no_token_for_other_hosts():
    vault = Vault()
    vault.set("GITHUB_TOKEN", "ghp_secret123")
    fake = _FakeExecutor()
    await GitCloneTool(fake, vault=vault).run({"url": "https://evil.example/github.com/x.git"})
    assert not any("extraHeader" in a for a in fake.calls[0])


async def test_output_truncated():
    fake = _FakeExecutor(SandboxResult(0, "x" * 30_000, ""))
    out = await GitRepoTool(fake).run({"action": "log", "repo": "r"})
    assert out.endswith("(10000 more chars truncated)")
