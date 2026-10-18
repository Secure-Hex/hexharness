"""Git repository tools. git always runs INSIDE the session sandbox container (cloned
repos are untrusted), with argv lists — never a shell string.

- git_clone: clone/pull a remote repo into /workspace. ACTIVE + requires_approval (network
  to an arbitrary forge host, like cloud_storage_enum). Not scope-sensitive: forges are
  third-party sources (github_dork convention), and the operator sees the URL on approval.
- git_repo:  read-only inspection of a repo under /workspace (log, grep, blame, pickaxe…).
  PASSIVE, no approval — it never touches the network.

Two tools, not one: risk/approval are static per tool in the control plane, so a single
tool would force approval on every read (same split as postman_list/postman_run).

Hardening: hooks disabled, fsmonitor off, no pager/ext-diff/textconv, no prompts (HTTPS or
SSH), no submodule recursion, every user value that could be read as an option is
rejected if it starts with '-' or placed after '--'.
"""
from __future__ import annotations

import base64
import posixpath
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from hexharness.sandbox.executor import SandboxError, SandboxExecutor
from hexharness.tools.base import RiskLevel, Tool

WS = "/workspace"
MAX_OUT = 20_000  # ponytail: char cap on output; raise if a turn needs more
_SCHEMES = ("https://", "http://", "ssh://", "git://", "git@")
# Optional auth for the big public forges: used only if the operator already put the
# secret in the Vault (never prompted). Self-hosted forges clone unauthenticated.
_TOKENS = {
    "github.com": ("GITHUB_TOKEN", "x-access-token"),
    "gitlab.com": ("GITLAB_TOKEN", "oauth2"),
    "bitbucket.org": ("BITBUCKET_TOKEN", "x-token-auth"),
}


def _git(*args: str) -> list[str]:
    return ["env", "GIT_TERMINAL_PROMPT=0",
            "GIT_SSH_COMMAND=ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
            "git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-c", "safe.directory=*", "-c", "submodule.recurse=false", "--no-pager", *args]


def _ws_path(rel: str) -> str:
    """Resolve a path inside the container's /workspace; refuse anything that escapes."""
    p = posixpath.normpath(posixpath.join(WS, rel))
    if p != WS and not p.startswith(WS + "/"):
        raise ValueError(f"path escapes {WS}: {rel!r}")
    return p


def _opt_safe(value: str, what: str) -> str:
    if value.startswith("-"):
        raise ValueError(f"{what} must not start with '-': {value!r}")
    return value


def _fmt(result, secrets: list[str] = ()) -> str:
    out = (result.stdout + result.stderr).strip()
    for s in secrets:
        out = out.replace(s, "***REDACTED***")
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n... ({len(out) - MAX_OUT} more chars truncated)"
    return out if result.ok else f"exit {result.exit_code}\n{out}"


class _GitTool(Tool):
    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "hexharness/kali:latest",
                 workspace: str | None = None, hardware: bool = False, host_network: bool = False, vault=None):
        self.executor = executor or SandboxExecutor()
        self.image = image
        self.workspace = workspace
        self.hardware = hardware  # must match exec_command: whoever starts the container sets it
        self.host_network = host_network  # likewise — same session container, same netns
        self.vault = vault

    async def _exec(self, argv: list[str], timeout: int):
        return await self.executor.exec_in_session(
            self.image, argv, timeout=timeout, workspace=self.workspace,
            hardware=self.hardware, host_network=self.host_network)


# --------------------------------------------------------------------- git_clone --

class GitCloneInput(BaseModel):
    action: Literal["clone", "pull"] = Field(default="clone", description="clone a URL, or pull an existing repo")
    url: str | None = Field(default=None, description="clone: https://, http://, ssh://, git:// or git@host:path URL")
    ref: str | None = Field(default=None, description="clone: branch or tag to check out")
    depth: int = Field(default=1, description="clone: history depth (0 = full history, needed for history_search)")
    repo: str | None = Field(default=None, description="Repo dir relative to /workspace. clone default: repos/<name>; pull: required")


class GitCloneTool(_GitTool):
    name = "git_clone"
    description = ("Clone a git repo (GitHub/GitLab/Gitea/Bitbucket/any git URL) into /workspace/repos/<name> "
                   "inside the sandbox, or pull an existing one. Uses GITHUB_TOKEN/GITLAB_TOKEN/BITBUCKET_TOKEN "
                   "from the vault for private repos on those hosts if set. Inspect with git_repo. Requires approval.")
    input_model = GitCloneInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = False
    requires_approval = True

    def _auth(self, url: str) -> tuple[list[str], list[str]]:
        """-c args carrying a host-scoped auth header, plus the strings to redact."""
        if self.vault is None or not url.startswith("https://"):
            return [], []
        host = (urlsplit(url).hostname or "").lower()
        if host not in _TOKENS or not self.vault.has(_TOKENS[host][0]):
            return [], []
        secret, user = _TOKENS[host]
        token = self.vault.get(secret)
        b64 = base64.b64encode(f"{user}:{token}".encode()).decode()
        # Header (not URL) so the token never lands in .git/config; host-scoped so a
        # redirect to another host does not receive it.
        return ["-c", f"http.https://{host}/.extraHeader=Authorization: Basic {b64}"], [token, b64]

    async def run(self, tool_input: dict) -> str:
        try:
            if tool_input.get("action", "clone") == "pull":
                return await self._pull(tool_input)
            return await self._clone(tool_input)
        except SandboxError as e:
            return f"sandbox unavailable: {e}"

    async def _clone(self, tool_input: dict) -> str:
        url = (tool_input.get("url") or "").strip()
        _opt_safe(url, "url")
        if not url.startswith(_SCHEMES):
            raise ValueError(f"unsupported git URL (allowed: {', '.join(_SCHEMES)}): {url!r}")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", re.split(r"[/:]", url.rstrip("/"))[-1].removesuffix(".git"))
        dest = _ws_path(tool_input.get("repo") or f"repos/{name.lstrip('.') or 'repo'}")
        auth, secrets = self._auth(url)
        args = ["clone", "--no-recurse-submodules"]
        if (depth := int(tool_input.get("depth", 1))) > 0:
            args += ["--depth", str(depth)]
        if ref := tool_input.get("ref"):
            args += ["--branch", _opt_safe(ref, "ref")]
        result = await self._exec(_git(*auth, *args, "--", url, dest), timeout=300)
        out = _fmt(result, secrets)
        return f"cloned into {dest}\n{out}".strip() if result.ok else out

    async def _pull(self, tool_input: dict) -> str:
        if not tool_input.get("repo"):
            raise ValueError("pull needs 'repo'")
        repo = _ws_path(tool_input["repo"])
        remote = await self._exec(_git("-C", repo, "remote", "get-url", "origin"), timeout=30)
        auth, secrets = self._auth(remote.stdout.strip()) if remote.ok else ([], [])
        return _fmt(await self._exec(_git(*auth, "-C", repo, "pull", "--ff-only"), timeout=300), secrets) or "ok"


# ---------------------------------------------------------------------- git_repo --

class GitRepoInput(BaseModel):
    action: Literal["status", "log", "show", "diff", "grep", "ls_files", "blame",
                    "branches", "tags", "history_search"]
    repo: str = Field(description="Repo dir relative to /workspace, e.g. 'repos/hello-world'")
    rev: str | None = Field(default=None, description="Revision: log/grep/ls_files/blame start point, "
                            "show object (e.g. 'HEAD~2' or 'HEAD:path'), diff range (e.g. 'a..b')")
    path: str | None = Field(default=None, description="Limit to this path (blame: required; show: rev:path)")
    pattern: str | None = Field(default=None, description="grep / history_search pattern")
    regex: bool = Field(default=False, description="history_search: regex match on diff lines (-G) "
                        "instead of string add/remove count (-S)")
    n: int = Field(default=20, description="log / history_search: max commits")


class GitRepoTool(_GitTool):
    name = "git_repo"
    description = ("Inspect a git repo under /workspace (read-only, no network): status, log, show, diff, "
                   "grep, ls_files, blame, branches, tags, history_search (pickaxe `git log -S/-G -p --all`, "
                   "finds secrets removed from history; clone with depth=0 first). Clone with git_clone.")
    input_model = GitRepoInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    @staticmethod
    def _argv(tool_input: dict) -> list[str]:
        action = tool_input["action"]
        rev = tool_input.get("rev")
        rev_args = [_opt_safe(rev, "rev")] if rev else []
        path = tool_input.get("path")
        paths = ["--", path] if path else ["--"]
        n = f"-n{max(1, int(tool_input.get('n', 20)))}"
        fmt = ["--format=%h %ad %an <%ae>%n    %s", "--date=short"]
        pattern = tool_input.get("pattern")
        if action in ("grep", "history_search") and not pattern:
            raise ValueError(f"{action} needs 'pattern'")
        if action == "status":
            args = ["status", "--short", "--branch"]
        elif action == "log":
            args = ["log", n, *fmt, *rev_args, *paths]
        elif action == "show":
            obj = _opt_safe(f"{rev or 'HEAD'}:{path}" if path else (rev or "HEAD"), "rev")
            args = ["show", "--no-ext-diff", "--no-textconv", obj]
        elif action == "diff":
            args = ["diff", "--no-ext-diff", "--no-textconv", *rev_args, *paths]
        elif action == "grep":
            args = ["grep", "-n", "-I", "-e", pattern, *rev_args, *paths]
        elif action == "ls_files":
            args = ["ls-tree", "-r", "--name-only", *rev_args, *paths] if rev else ["ls-files", *paths]
        elif action == "blame":
            if not path:
                raise ValueError("blame needs 'path'")
            args = ["blame", *rev_args, *paths]
        elif action == "branches":
            args = ["branch", "-a", "-vv"]
        elif action == "tags":
            args = ["tag", "-l", "-n1"]
        else:  # history_search
            pick = ("-G" if tool_input.get("regex") else "-S") + pattern  # one argv token: never an option
            args = ["log", pick, "--all", "-p", "--no-ext-diff", "--no-textconv", n, *fmt, *paths]
        return _git("-C", _ws_path(tool_input["repo"]), *args)

    async def run(self, tool_input: dict) -> str:
        argv = self._argv(tool_input)
        try:
            result = await self._exec(argv, timeout=60)
        except SandboxError as e:
            return f"sandbox unavailable: {e}"
        return _fmt(result) or "(no output)"
