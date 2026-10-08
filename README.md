# HexHarness

Agentic pentesting harness. The differentiator is not the agent loop (that is standard)
but a **domain control plane** — scope, ROE, evidence, approvals, budget — that is
unbreakable by design. Dual-use by nature; what keeps it on the right side is that the
Scope Guard + ROE are hard gates and everything lands in the hash-chained audit log.

## Install

```bash
python -m venv venv && ./venv/bin/pip install -e '.[dev]'
./venv/bin/pytest -q          # 252 passed, 3 skipped (optional-dep paths)
```

Core + tests run with no optional dependency installed; every integration is lazy-imported.

## Quickstart (TUI)

```bash
./venv/bin/pip install -e '.[tui]'
./venv/bin/python -m hexharness tui                 # start blank — describe a target to configure it
./venv/bin/python -m hexharness tui --engagement engagements/example.engagement.yaml
```

Launched without `--engagement` the TUI starts **unconfigured**: no scope, no resumed
history. Describe the target and the model drafts an engagement; you approve the scope/ROE
in a dialog before anything runs. Each turn auto-saves; reopening resumes the session.

Key bindings: `Ctrl+P` provider · `Ctrl+E` edit engagement (scope/ROE/budget/sandbox/hardware)
· `Ctrl+O` mode · `Ctrl+T` capabilities · `Ctrl+F` findings · `Ctrl+G` generate report
· `Ctrl+R` dictate · `Ctrl+K` kill switch · `Ctrl+X` cancel turn · drag to select, `Ctrl+C` copies.

## CLI

```bash
# run one task against an existing engagement
ANTHROPIC_API_KEY=sk-... ./venv/bin/python -m hexharness run \
    "Look up CWE-79 and explain it" --engagement engagements/example.engagement.yaml \
    --autonomy interactive --phase recon

# draft a new engagement from a natural-language brief, confirm, then run it
ANTHROPIC_API_KEY=sk-... ./venv/bin/python -m hexharness init \
    "External test of acme.example and 203.0.113.0/24, exclude vpn.acme.example, \
     enumeration only, business hours" --task "Resolve www.acme.example"

./venv/bin/python -m hexharness build-image     # build the Kali sandbox image (Kali + tools)
./venv/bin/python -m hexharness verify  --engagement <file>   # verify the audit log hash chain
./venv/bin/python -m hexharness report  --engagement <file> --out report.html
```

The requested `--autonomy/--phase` are clamped to the engagement's ROE ceiling. The agent
can never grant itself scope or ROE: `init` drafting writes an inert file, and activation
is a human step (invariants #3/#4).

## The non-negotiable invariants (each has a test)

1. The agent loop never calls `tool.run()` directly — always `ControlPlane.authorize()` first.
2. `authorize()` order: `scope_guard → mode.decide(risk) → roe.cap → budget → HITL → secrets`, fail-closed.
3. Scope Guard is a hard gate no mode bypasses — not even `bypass`. Out of scope = deny.
4. ROE sets the engagement's max mode (immutable); active mode = `min(requested, ceiling)`.
5. Findings enter as CANDIDATE; only CONFIRMED reach the report; REJECTED kept with reason.
6. Kill switch is out-of-band (signal / trigger file), works client-disconnected, checkpoints first.
7. Secrets are acquired out-of-band; their values never reach the model or the logs — only names.

Audit log, tracing and checkpointing are **projections** of one append-only, hash-chained
event stream (`hexharness/events/`). `hexharness verify` walks the chain and flags tampering.

## Capabilities (tools)

The agent drives tools through the control plane; `knowledge_search` and the skills library
document each one. Current toolset:

- **Recon** — `dns_enum`, `dns_lookup`, `whois_lookup`, `port_scan`, `parallel_scan`
  (concurrent multi-host, scope-enforced), `banner_grab`, `ssh_info`, `ftp_check`,
  `http_probe`, `smb_enum`, `browser` (Playwright: interact + screenshots).
- **OSINT** — `web_search` (DuckDuckGo free / Tavily / Exa), `shodan_host`, `wayback_urls`,
  `github_dork`, `cloud_storage_enum` (S3/Azure/GCS).
- **Exploitation / C2** — `exec_command` (sandboxed, session-persistent), `exploit_run`
  (scope-checked), `msfvenom_payload`, and the reverse-shell handler
  (`listener_start` / `shell_sessions` / `shell_exec` / `listener_stop`).
- **Analysis** — `binary_info`, `checksec`, `disassemble`, `postman_list`, `postman_run`.
- **Evidence / reporting** — `record_finding`, `list_findings`, `generate_report`.
- **Orchestration / meta** — `run_workflow` (declarative pipeline: templating, `for_each`,
  conditions — every step still passes the control plane), `skill_lookup`, `skill_install`
  (project or global scope), `knowledge_search`, `cwe_lookup`, `mitre_attack_lookup`,
  `mcp_connect`, `engagement_draft`, `file_read`, `file_write`.

Offensive tools are `DESTRUCTIVE`/`INTRUSIVE` + `requires_approval` and, where a target is
involved, scope-sensitive. A caught reverse shell whose peer IP is out of scope is dropped
on connect.

## Sandbox

`exec_command` runs in a **long-lived Docker container per session** (installs/state persist
across calls; only the host-mounted `/workspace` survives after the session ends). The bundled
image `hexharness/kali:latest` builds from `sandbox/docker/Dockerfile` (ships in the wheel,
auto-builds on first use): Kali + nmap/smbclient/curl/metasploit-framework/aircrack-ng/etc.

`engagement.hardware_access` (opt-in, default off) passes host USB/UART + wireless NICs into
the session container (`--privileged`, host net) for hardware and WiFi work — it drops the
sandbox isolation, so it is explicit. Scanners keep ephemeral, hardened containers.

## Knowledge base

- `mitre_attack_lookup` — the full MITRE ATT&CK Enterprise catalog (~697 techniques).
- `cwe_lookup` — the full MITRE CWE catalog (~969 weaknesses).
- `knowledge_search` — TF-IDF RAG over a local markdown corpus (technique playbooks + a
  per-capability tool reference + the workflow guide).
- Skills library (`skill_lookup`) — runnable playbooks (sqli-triage, subdomain-enumeration,
  workflow-chaining, reverse-shell-handler, exploitation); install more at project or global scope.

## Secrets

Out-of-band vault: a tool that needs a key (`shodan_host`, `github_dork`, paid web search,
MCP servers) triggers an operator prompt; the value is stored and reused, **never** shown to
the model or logged. With the `[secrets]` extra it persists **encrypted at rest** (Fernet,
per engagement); without it, in-memory only.

## Layout

```
hexharness/
  providers/   normalized LLM types + Anthropic/OpenAI/Google/Ollama adapters + router (+ fake)
  agent/       ExecContext, single-agent loop (the chokepoint), workflow engine, orchestrator
  control/     THE control plane: plane, scope_guard, policy(modes), roe, budget, hitl, kill_switch, vault
  events/      append-only log + SHA-256 hash chain + bus
  tools/       Tool base + registry + native tools + MCP client
  sandbox/     Docker executor (hardened; argv list, no shell) + packaged Kali image
  evidence/    findings (candidate/confirmed/rejected) + store
  knowledge/   MITRE ATT&CK + CWE data + TF-IDF RAG corpus
  skills/      skill engine + bundled playbook library
  reporting/   ReportModel (from confirmed findings) + Jinja/DOCX render
  tui/         Textual terminal UI
  observability/ OTel span projection    recovery/ snapshot + replay
  protocol/ transport/ daemon/ client/   JSON-RPC client/daemon split (sessions attach/resume)
  engagement.py  engagement.yaml -> control-plane objects     engine.py  composition root
```

## Optional dependencies

```bash
./venv/bin/pip install -e '.[all]'   # everything
# or pick: tui / openai / google / otel / daemon / reporting / mcp / browser / secrets / voice
```

`browser` also needs `./venv/bin/playwright install chromium`.

## Known ceilings (marked `ponytail:` in code)

- Orchestrator workers run sequentially (swap to `asyncio.gather` + per-worker providers).
- Knowledge RAG is a linear TF-IDF scan (fine for a local corpus; add a vector index if it grows).
- `run_workflow` passes values as text (no structured outputs); `for_each` splits on lines/commas.
- Reverse-shell output is read by idle-timeout (no PTY/prompt detection); keep commands non-interactive.
- MCP tools default to INTRUSIVE + requires_approval unless a `classify` override says otherwise.
- `.md`→PDF and DOCX→PDF need extra converters; HTML→PDF via WeasyPrint is the primary path.
