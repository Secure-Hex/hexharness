# Writing HexHarness Modules

HexHarness is an async Python 3.12 agentic pentesting harness. You extend it by
writing **modules**: tools, MCP connections, skills, and LLM providers. This guide
teaches each one against the real APIs in the codebase.

## The one rule that governs everything: the control plane

Every capability the model can reach is **gated**. The agent loop *never* calls a
tool's `run()` directly. It calls `ControlPlane.authorize()` first, and only the
executor runs the tool — and only when `authorize()` returned `ALLOW`. This is
invariant #1, enforced and tested (`tests/test_authorize_chokepoint.py`).

A `Tool` declares its own risk posture in a few class attributes. The model never
sees those attributes — they exist purely for the control plane:

```python
# hexharness/tools/base.py
class Tool(ABC):
    """A tool declares its own risk posture. These three fields are what the control
    plane reads — the model never sees them."""

    name: str
    description: str
    input_model: type[BaseModel]
    risk_level: RiskLevel
    scope_sensitive: bool
    requires_approval: bool = False
    # Name of the input field that holds the scope target (host/ip/url). Required
    # when scope_sensitive is True so the Scope Guard knows what to check.
    target_field: str | None = None
    # Secrets this tool needs present in the Vault before it may run. If one is missing,
    # the control plane asks the operator out-of-band (never the model) and stores it.
    required_secrets: list[str] = []
```

### The authorize() order (fixed, fail-closed)

`ControlPlane.authorize()` runs the gates in a fixed order; any exception anywhere
denies, and every decision is written to the event log:

```
1. scope_guard(target)     # hard gate — NO mode bypasses it, not even BYPASS
2. mode.decide(risk)       # autonomy + phase ceiling
3. roe.cap(decision, risk) # Rules of Engagement ceiling + time window (can only tighten)
4. budget                  # deny if any cap is spent
5. HITL                    # resolve ASK, and ALWAYS confirm a requires_approval tool
6. secrets                 # resolve required_secrets out-of-band into the Vault
```

The key facts a module author must internalise, straight from `plane.py`:

- **Scope is first and absolute.** If `tool.scope_sensitive`, the guard extracts the
  target via `tool.extract_target(tool_input)` and denies anything out of scope. No
  autonomy mode, not even `BYPASS`, gets past it.
- **`requires_approval=True` always forces a human confirmation** when the decision
  isn't already a deny — even in `AUTO`/`BYPASS`.
- **Secret values never reach the model or the event log.** Only the secret's *name*
  is recorded (`EventType.SECRET_PROVIDED`).

### The risk tiers

```python
# hexharness/tools/base.py
class RiskLevel(IntEnum):
    PASSIVE = 0       # read-only, no packets at target (lookups, local parsing)
    ACTIVE = 1        # touches target benignly (dns, banner grab, light enum)
    INTRUSIVE = 2     # exploit attempts, auth brute, injection
    DESTRUCTIVE = 3   # data modification/deletion, DoS-capable
```

The ordering is load-bearing: the phase ceiling and ROE ceiling both use
`risk > ceiling` comparisons. Each engagement phase pins a maximum risk
(`RECON→PASSIVE`, `ENUMERATION→ACTIVE`, `EXPLOITATION→INTRUSIVE`,
`POST_EXPLOITATION→DESTRUCTIVE`, `REPORTING→PASSIVE`), so a tool riskier than the
current phase is denied regardless of autonomy. **Pick the honest tier** — understating
risk defeats the phase and ROE ceilings that are meant to protect the engagement.

---

## Module type 1: a native Tool

**When to use it.** Any new capability the agent should be able to invoke directly:
a lookup, a probe, a file operation, a scan.

**The contract.** Subclass `Tool`, set the class attributes, declare a pydantic
`input_model`, and implement `async run(self, tool_input: dict) -> str`. `run` always
returns a string (that becomes the `tool_result` the model sees). It must **never** be
called directly — only the executor calls it, only after `authorize()` returned ALLOW.

### Worked example: passive, simplest possible

`CweLookupTool` is the template for a passive, non-scope-sensitive tool — a real tool
over static reference data, not a mock:

```python
# hexharness/tools/native/knowledge.py
from pydantic import BaseModel, Field
from hexharness.tools.base import RiskLevel, Tool


class CweLookupInput(BaseModel):
    cwe_id: str = Field(description="CWE numeric id, e.g. '79' or 'CWE-79'")


class CweLookupTool(Tool):
    name = "cwe_lookup"
    description = "Look up a CWE weakness by id. Returns its name and a one-line description."
    input_model = CweLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        cid = str(tool_input.get("cwe_id", "")).upper().replace("CWE-", "").strip()
        ...  # returns a plain string
```

### A minimal, complete new tool

```python
# hexharness/tools/native/mytool.py
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool


class HttpHeadersInput(BaseModel):
    url: str = Field(description="URL to fetch response headers from (must be in scope)")


class HttpHeadersTool(Tool):
    name = "http_headers"
    description = "Fetch the HTTP response headers of a URL (no body)."
    input_model = HttpHeadersInput
    risk_level = RiskLevel.ACTIVE      # it touches the target benignly
    scope_sensitive = True             # it reaches a target, so the Scope Guard must vet it
    requires_approval = False
    target_field = "url"               # REQUIRED because scope_sensitive is True

    async def run(self, tool_input: dict) -> str:
        url = tool_input["url"]
        # ... do the real work (async), return a string
        return f"headers for {url}: ..."
```

### How to register it

Tools live in a `ToolRegistry`. Registration enforces one rule: a `scope_sensitive`
tool **must** declare a `target_field`, or registration raises:

```python
# hexharness/tools/registry.py
def register(self, tool: Tool) -> None:
    if tool.name in self._tools:
        raise ValueError(f"tool already registered: {tool.name}")
    if tool.scope_sensitive and not tool.target_field:
        raise ValueError(f"{tool.name} is scope_sensitive but declares no target_field")
    self._tools[tool.name] = tool
```

The composition root wires the default toolset in `engine.default_registry()`. Add
your tool there so every engagement gets it:

```python
# hexharness/engine.py  (inside default_registry)
reg.register(CweLookupTool())
...
reg.register(DnsLookupTool())
reg.register(PortScanTool(executor))
# add yours:
reg.register(HttpHeadersTool())
```

For a one-off, build your own registry and pass it to `Engine.from_engagement(...,
registry=reg)`.

### Risk / approval guidance

- `PASSIVE` → usually auto-allowed even in `INTERACTIVE` mode. Use it only for
  read-only, no-packets-at-target work.
- `ACTIVE` → benign contact with the target (DNS, header grab). Auto in `AUTO` mode,
  asks in `INTERACTIVE`.
- `INTRUSIVE` / `DESTRUCTIVE` → set `requires_approval = True`. These always trigger a
  human confirmation when not already denied.

---

## Module type 2: scope-sensitive and sandboxed tools

**When to use it.** Anything that sends traffic to a target (scope-sensitive), and
anything that runs external binaries or writes to disk (sandbox / workspace
confinement).

### Scope-sensitive: how the target is extracted

Set `scope_sensitive = True` and name the input field that carries the target in
`target_field`. The base class does the extraction; the Scope Guard does the check:

```python
# hexharness/tools/base.py
def extract_target(self, tool_input: dict) -> str | None:
    if not self.scope_sensitive or not self.target_field:
        return None
    return tool_input.get(self.target_field)
```

`DnsLookupTool` is the canonical scope-sensitive example — real stdlib resolution,
`target_field = "host"`:

```python
# hexharness/tools/native/net.py
class DnsLookupTool(Tool):
    name = "dns_lookup"
    description = "Resolve a hostname to its A/AAAA records."
    input_model = DnsLookupInput
    risk_level = RiskLevel.ACTIVE
    scope_sensitive = True
    requires_approval = False
    target_field = "host"

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
        addrs = sorted({i[4][0] for i in infos})
        return f"{host} -> {', '.join(addrs)}" if addrs else f"{host}: no records"
```

The Scope Guard parses hosts out of URLs, strips ports, matches domains and CIDRs, and
**fails closed**: an empty/unparseable target or one matching no allow rule is denied
(`scope_guard.py`).

### Sandboxed: run external tooling in Docker, never on the host

`PortScanTool` runs `nmap` inside the sandbox. It is `INTRUSIVE + requires_approval`
and scope-sensitive. The executor is injected (so tests can pass a fake):

```python
# hexharness/tools/native/net.py
class PortScanTool(Tool):
    name = "port_scan"
    description = "TCP port scan via nmap (sandboxed). Intrusive — requires approval."
    input_model = PortScanInput
    risk_level = RiskLevel.INTRUSIVE
    scope_sensitive = True
    requires_approval = True
    target_field = "host"

    def __init__(self, executor: SandboxExecutor | None = None, *, image: str = "instrumentisto/nmap"):
        self.executor = executor or SandboxExecutor()
        self.image = image

    async def run(self, tool_input: dict) -> str:
        host = tool_input["host"]
        ports = tool_input.get("ports", "1-1000")
        result = await self.executor.run(
            self.image, ["-p", ports, "-Pn", host], network="bridge", timeout=180
        )
        return result.stdout if result.ok else f"scan failed (exit {result.exit_code}): {result.stderr}"
```

`ExecCommandTool` runs arbitrary commands, always in the sandbox, `DESTRUCTIVE +
requires_approval`. Note the injection-safety invariant: **argv is forwarded as a
list**, never assembled into a shell string:

```python
# hexharness/tools/native/exec.py
class ExecCommandInput(BaseModel):
    argv: list[str] = Field(description="Command and args as a list (no shell), e.g. ['id']")
    network: str = Field(default="none", description="Docker network mode ('none' or 'bridge')")
    timeout: int = Field(default=60, description="Seconds before the container is killed")
```

### Workspace confinement: the one chokepoint for path trust

`FileReadTool` / `FileWriteTool` route every path through a single
`_resolve_in_workspace` method that rejects `..` traversal, absolute escapes, and
symlinks pointing out of the root (because `Path.resolve()` follows links):

```python
# hexharness/tools/native/fs.py
class _WorkspaceConfined:
    """Shared confinement. The single place path trust is decided."""

    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def _resolve_in_workspace(self, path: str) -> Path:
        candidate = (self.workspace / path).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise ValueError(f"path escapes workspace: {path!r}")
        return candidate
```

Read is `ACTIVE` (benign); write is `INTRUSIVE + requires_approval` (can plant/clobber).
When you write a tool that touches the filesystem, confine it the same way — one
chokepoint, not a check scattered across callers.

### Registration & testing

Register exactly as in type 1. Sandboxed tools take the executor in their constructor,
so `default_registry()` wires a shared `SandboxExecutor()` and passes it in. For testing,
see the testing section — the rule is **the real tool and real sandbox are not mocked**;
you inject a fake *executor* only to assert argv safety, and guard the real-Docker test
with `@pytest.mark.skipif(shutil.which("docker") is None, ...)`.

---

## Module type 3: runtime extension (model-driven registry mutation)

**When to use it.** Tools that let the *model*, by chatting, grow its own capabilities
at runtime — installing a skill or connecting an MCP server. These mutate the live
registries. See `hexharness/tools/native/extend.py`.

**The contract is unchanged.** They are ordinary `Tool`s, both `requires_approval=True`.
Nothing bypasses authorization: the model proposes, the control plane disposes.

`SkillInstallTool` writes a new skill into the live `SkillRegistry` so the existing
`skill_lookup` tool sees it next turn. `McpConnectTool` connects an MCP server and folds
its remote tools into the live `ToolRegistry` through the same control plane. It also
demonstrates the **per-invocation out-of-band secret path**: it fills any `secret_env`
the vault lacks by asking the `SecretRequester`, and aborts *before* connecting if the
operator cancels — never leaking the value:

```python
# hexharness/tools/native/extend.py  (McpConnectTool.run, excerpt)
for secret_name in data.secret_env:
    if self._vault.has(secret_name):
        continue
    value = await self._secrets.request(
        name=secret_name, reason=f"MCP server '{data.command}' requires it"
    )
    if value is None:
        return f"aborted: secret '{secret_name}' was not provided; did not connect to {data.command}"
    self._vault.set(secret_name, value)
```

Acknowledge secrets **by name only** in the return string — values never appear there.

These tools take the live registries/vault in their constructor and are wired in
`default_registry()`:

```python
# hexharness/engine.py
reg.register(SkillInstallTool(skills, library))
reg.register(McpConnectTool(reg, vault, secret_requester))
```

---

## Module type 4: MCP tools

**When to use it.** To expose a third-party MCP server's tools to the agent. MCP is the
harness's primary tool protocol — a discovered MCP tool is wrapped as a first-class
`Tool` and registered through the *same* `ToolRegistry`, so the control plane can't tell
it from a native tool (`hexharness/tools/mcp.py`).

**The contract.** `MCPTool` sets its attributes per-instance (each wraps a different
remote tool) and delegates `run` to the client's `call_tool`. You rarely write it
directly — you call `register_mcp_tools(registry, client, classify=...)`.

### Conservative default risk

MCP doesn't declare pentest risk, so every unclassified remote tool defaults to the
locked-down posture:

```python
# hexharness/tools/mcp.py
_DEFAULT: Classification = (RiskLevel.INTRUSIVE, False, True, None)
#                           risk,                scope,  approval, target_field
```

### Classify overrides

Pass a `classify(name) -> Classification | None` callback to relax or tighten specific
tools. `None` keeps the conservative default. A `Classification` is the tuple
`(risk_level, scope_sensitive, requires_approval, target_field)`:

```python
from hexharness.tools.base import RiskLevel
from hexharness.tools.mcp import register_mcp_tools, StdioMCPClient

def classify(name: str):
    if name == "echo":
        return (RiskLevel.PASSIVE, False, False, None)
    if name == "http_get":
        return (RiskLevel.ACTIVE, True, True, "url")  # scope_sensitive => target_field required
    return None  # everything else stays INTRUSIVE + approval

client = StdioMCPClient("my-mcp-server", ["--flag"])
await client.connect()
wrapped = await register_mcp_tools(registry, client, classify=classify)
```

Registering a scope-sensitive MCP tool with no `target_field` is rejected by the same
registry invariant as native tools — the MCP wrapper honours it (`tests/test_mcp.py`).

The `mcp` SDK is lazy-imported (optional dep `[mcp]`), so the module imports without it;
tests use `FakeMCPClient` and never touch the SDK or a subprocess.

---

## Module type 5: skills

**When to use it.** To give the agent a reusable playbook (prose procedure), not a new
executable capability. Skills are discovered by the engine and surfaced to the model
through the passive `skill_lookup` tool with **progressive disclosure**: the agent sees
every skill's one-line metadata for free and pays the token cost of a full playbook only
on demand (`hexharness/skills/engine.py`).

**The contract.** A skill is a directory under `hexharness/skills/library/<name>/`
holding two files:

- `skill.yaml` — cheap metadata, always loadable into context.
- `playbook.md` — the full prose body, loaded only when the skill is selected.

### A complete skill

```yaml
# hexharness/skills/library/subdomain-enumeration/skill.yaml
name: subdomain-enumeration
description: Enumerate subdomains of an in-scope apex domain and triage which hosts are live.
version: 0.1.0
phase: recon
tags: [recon, dns, attack-surface, osint]
risk_hint: active
```

The manifest schema (`SkillManifest`) requires `name`, `description`, and `phase`;
`version`, `tags`, and `risk_hint` have defaults. **`risk_hint` is advisory only** — it
documents the playbook's posture, but the control plane still authorizes every tool call
the playbook makes independently.

```markdown
<!-- hexharness/skills/library/subdomain-enumeration/playbook.md -->
# Subdomain Enumeration

Goal: map the subdomain attack surface of an in-scope apex domain...

## Preconditions
- An apex domain (e.g. `example.com`) that is explicitly in scope.
- ROE permits at least PASSIVE+ACTIVE recon for this phase.

## Steps
1. Passive collection (no packets at target)...
2. Resolve...

## Output
A table of `subdomain → IP → open web ports → title/status`...

## Pitfalls
- Wildcard DNS producing phantom hosts...
```

### How it gets registered

`default_registry()` discovers the whole library directory and wires one
`SkillLookupTool` over it; no per-skill registration is needed — dropping the directory
in is enough:

```python
# hexharness/engine.py
library = Path(__file__).parent / "skills" / "library"
skills = SkillRegistry().discover(library)
reg.register(SkillLookupTool(skills))
```

At runtime the model can also author a skill into the live registry via
`skill_install` (see type 3). `SkillRegistry.discover` raises on a duplicate name.

---

## Module type 6: LLM providers

**When to use it.** To add a new model backend. The rest of the engine only ever sees
the normalized types in `hexharness/providers/types.py` — never a vendor SDK object.

**The contract: implement the `LLMProvider` Protocol.**

```python
# hexharness/providers/base.py
TextSink = Callable[[str], None]  # called with each text delta; None = no streaming

@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        on_text: TextSink | None = None,
    ) -> ModelResponse: ...
```

Your adapter must:

1. **Map normalized → vendor** on the way in (messages, tools) and **vendor →
   normalized** on the way out (into a `ModelResponse` with `content`, `stop_reason`,
   `usage`, `model`).
2. **Lazy-import the vendor SDK** inside `__init__` (or the call) so the package imports
   without that optional dependency installed.
3. **Honour the `on_text` streaming sink**: when it's not `None`, stream text deltas to
   it and still return the full mapped `ModelResponse`.

### The Anthropic adapter as the template

```python
# hexharness/providers/anthropic.py (excerpt)
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, default_model: str | None = None):
        from anthropic import AsyncAnthropic  # lazy import — package imports without the SDK
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=key)
        self.default_model = default_model or os.environ.get("HEXHARNESS_MODEL", "claude-sonnet-4-5")

    async def complete(self, messages, *, tools=None, system=None, model=None, max_tokens=4096, on_text=None):
        kwargs = {"model": model or self.default_model, "max_tokens": max_tokens,
                  "messages": to_api_messages(messages)}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description,
                                "input_schema": t.input_schema} for t in tools]
        if on_text is not None:
            async with self._client.messages.stream(**kwargs) as stream:
                async for delta in stream.text_stream:
                    on_text(delta)                       # stream deltas to the sink
                final = await stream.get_final_message()
            return from_api_response(final)              # still return the full response
        resp = await self._client.messages.create(**kwargs)
        return from_api_response(resp)
```

`to_api_messages` and `from_api_response` are the normalized↔vendor mappers — write the
equivalents for your SDK. Note `ToolSpec` carries **no risk metadata** — risk lives on
the `Tool` and is the control plane's business, not the model's.

### Registration

Providers are passed in, not registered in a global table. Hand your provider to
`Engine.from_engagement(..., provider=MyProvider())`, or compose several behind the
cost-aware `Router` (`hexharness/providers/router.py`), which picks the cheapest route
advertising a capability and falls back on error. Optional SDKs go in
`pyproject.toml` `[project.optional-dependencies]` (e.g. `openai`, `google`).

---

## Testing convention

The suite runs under pytest with `asyncio_mode = "auto"` (`pyproject.toml`), so
`async def test_*` functions need no decorator.

### Use `FakeProvider` for the LLM — it is NOT a forbidden mock

```python
# hexharness/providers/fake.py
class FakeProvider:
    """Scripted provider. NOT a mock of real infrastructure — the "no mocks" invariant
    applies to tools and the sandbox (which must be real), not to the LLM in unit tests."""
    def __init__(self, scripted: list[ModelResponse]): ...
```

You script a list of `ModelResponse` objects (a `ToolUseBlock` to drive a tool call,
then a `TextBlock` to end the turn) and assert what the loop/control plane did:

```python
# pattern from tests/test_authorize_chokepoint.py
provider = FakeProvider([_tool_use("exploit"), _final("I was blocked")])
loop = AgentLoop(provider=provider, control=cp, registry=reg, events=events,
                 ctx=ctx(Mode(autonomy=Autonomy.INTERACTIVE, phase=Phase.EXPLOITATION)))
out = await loop.run("try it")
assert spy.ran is False                     # the invariant: denied => never executed
```

`tests/conftest.py` gives you `make_control(...)` and `ctx(mode)` helpers, and
`tests/_fakes.py` gives `SpyTool` (records whether `run()` fired — the chokepoint proof).

### The "no mocks for real tools / sandbox" rule

Real tools and the real sandbox are exercised directly — they are not mocked:

- `FileRead/WriteTool` are tested on a real `tmp_path` workspace, including escape
  attempts (`tests/test_fs_exec.py`).
- `ExecCommandTool` uses a tiny fake *executor* only to assert argv stays a list (no
  shell), while the **real Docker** path is a separate test guarded by
  `@pytest.mark.skipif(shutil.which("docker") is None, ...)`.
- MCP tools are tested with `FakeMCPClient` — never the real `mcp` SDK or a subprocess.

### Guard optional-dependency tests with `importorskip`

Any test that needs an optional dep must skip cleanly when it's absent, so the core
suite runs with no extras installed:

```python
import pytest
pytest.importorskip("textual")        # or "jinja2", "opentelemetry", "weasyprint", ...
```

---

## Security rules for module authors

1. **Never log or return secret values.** Acknowledge secrets by *name* only. The Vault
   redacts known values, but your tool must not place a secret into a return string,
   event payload, or anything the model sees.
2. **Declare `required_secrets`** (or, for dynamic cases, use the out-of-band
   `SecretRequester` like `McpConnectTool`). The control plane fetches the value
   out-of-band into the Vault; it never routes through a prompt or tool result.
3. **Pick the honest `risk_level`.** The phase and ROE ceilings depend on it.
   Understating risk is a control-plane bypass. When unsure, pick the higher tier.
4. **Set `scope_sensitive = True` and `target_field`** for anything that touches a
   target. Registration *rejects* a scope-sensitive tool with no `target_field`, and the
   Scope Guard is a hard gate no mode can bypass.
5. **Set `requires_approval = True`** for `INTRUSIVE`/`DESTRUCTIVE` work — it forces a
   human confirmation.
6. **Keep destructive work in the sandbox / confined workspace.** Run external binaries
   through `SandboxExecutor` (Docker, never the host), forward argv as a *list* (never a
   shell string), and route every filesystem path through a single confinement
   chokepoint like `_resolve_in_workspace`.
7. **Never call `tool.run()` directly** from outside the executor. Authorization must
   run first — that is the whole point of the harness.
