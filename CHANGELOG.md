# CHANGELOG


## v1.2.0 (2026-10-08)

### Features

- **tui**: Edit scope entries in the engagement editor
  ([`6f84fb6`](https://github.com/Secure-Hex/hexharness/commit/6f84fb6f02fc3826ad72dc744902523c607814d1))

The scope list only had Add/Remove. Added 'Edit selected': it loads the highlighted
  domain/CIDR/exclusion back into its group's input and drops it from the list, so the operator
  fixes the value and re-adds it — no delete-and-retype.


## v1.1.1 (2026-10-08)

### Bug Fixes

- Install hints show the PyPI command, not the source-only editable form
  ([`984db0a`](https://github.com/Secure-Hex/hexharness/commit/984db0a1246ae3632b24f3e85c26c1f50c6add59))

Messages said 'pip install -e .[extra]' which only works from a repo checkout; a pip-installed user
  got a misleading hint. Now 'pip install -U hexharness[extra]' for voice/search/browser, and the
  voice hint notes the PortAudio system lib.


## v1.1.0 (2026-10-08)

### Features

- Check PyPI for updates and offer to upgrade
  ([`a7307aa`](https://github.com/Secure-Hex/hexharness/commit/a7307aa33579f3c81475e6a524b0c4b73a9e3571))

On startup HexHarness compares the installed version against the latest on PyPI. CLI prints a
  one-line notice; the TUI shows it and binds Ctrl+U to run 'pip install -U hexharness' then prompt
  for a restart. The operator can always keep the current version — the check is best-effort, fails
  safe offline, and is disabled by HEXHARNESS_NO_UPDATE_CHECK=1. Numeric version compare (1.10 >
  1.9).


## v1.0.1 (2026-10-08)

### Bug Fixes

- **tui**: Ship styles.tcss in the wheel
  ([`d1826ef`](https://github.com/Secure-Hex/hexharness/commit/d1826eff08817836106fe931bfd0c0d8c3bf77e9))

The Textual stylesheet (hexharness/tui/styles.tcss) was not in package-data, so 'hexharness tui'
  crashed on a pip-installed copy with StylesheetError: unable to read CSS file .../tui/styles.tcss.
  Added tui/*.tcss to package-data.

### Continuous Integration

- Fix vault-persist tests on clean runner
  ([`2c7a7f2`](https://github.com/Secure-Hex/hexharness/commit/2c7a7f2347ff54f4472eaa1782eb6e70d20775ef))

The encrypted-vault tests need cryptography (the [secrets] extra), which CI's [dev] install lacked,
  so they failed on the runner. CI now installs .[dev,secrets] (exercising the encrypted path), and
  the three crypto-dependent tests skip gracefully when cryptography is absent (via the project's
  own _get_fernet check).


## v1.0.0 (2026-10-08)

### Bug Fixes

- Binary file_read corrupted the terminal
  ([`a07355f`](https://github.com/Secure-Hex/hexharness/commit/a07355f493000e3ee680090ce020d9add1e87495))

file_read decoded raw bytes, so reading an image sprayed control chars (ESC, etc.) and broke the
  TUI. Now it detects binary (NUL byte / high non-text ratio) and returns a summary instead of
  dumping. Defense in depth: the TUI _log strips terminal control characters (keeping tab/newline)
  from all tool output, so no tool can corrupt the terminal.

- **engagement**: Accept nested scope/roe/budget passed as JSON strings
  ([`362cea3`](https://github.com/Secure-Hex/hexharness/commit/362cea3050eb7bf404cedc814e6a80aef6b2b0ec))

Some models serialize nested tool-call objects as JSON strings, so engagement_draft failed with
  'Input should be a valid dictionary ... input_type=str' for scope and roe. EngagementSpec now
  coerces a JSON string into a dict/list before validation (scope/roe/budget + roe.windows); a
  non-JSON string still raises the normal clear error.

- **providers**: Recover from broken streams; add reasoning (on_thinking) sink
  ([`494dad0`](https://github.com/Secure-Hex/hexharness/commit/494dad01afc4a0bd1ab0425e763163247f628bc1))

Harden stream_openai: if a gateway ends the stream early (the "stream ended before completion" error
  seen on some OpenAI-compatible gateways), fall back to one blocking completion so the turn still
  succeeds; also guard malformed tool args. Capture reasoning_content/reasoning deltas and route
  them to a new on_thinking sink, threaded through the LLMProvider contract, every adapter, the
  router, AgentLoop and Engine.loop. Decouple engagement/scope tests from the user-editable example
  file via tests/data/sample.engagement.yaml.

- **tools**: Make ddgs a core dep so web_search works out of the box
  ([`c9e892a`](https://github.com/Secure-Hex/hexharness/commit/c9e892a676cd778a5f6f999f97fa533b09f8b2c3))

- **tools**: Port_scan ran '-sS' as the executable — prepend 'nmap' to argv
  ([`ed5b02e`](https://github.com/Secure-Hex/hexharness/commit/ed5b02e6339b74d0885068a6a5d3856e36e3768f))

The argv omitted the program name, which only worked on an image whose entrypoint was nmap. On the
  tooled hexharness/kali image (no such entrypoint) the first flag became the executable (exec '-sS'
  not found). Lead the argv with 'nmap' and default the tool to hexharness/kali:latest.

- **tui**: A turn can never hang the UI + startup resume notice
  ([`a465eaf`](https://github.com/Secure-Hex/hexharness/commit/a465eafbdf761737fd362d39b01d6e23aef1924f))

Wrap loop.run in asyncio.wait_for(600s) so no turn can hang the UI forever regardless of cause
  (provider, network, a stuck tool); timeout surfaces an error and the UI recovers. Give every
  provider client a 60s request timeout + max_retries=1 (plain float — the SDK bundles httpx2, not
  httpx) so an unreachable endpoint fails fast. Add a launch notice when a saved session exists for
  the engagement (it still resumes lazily on the first prompt). Also import asyncio (was referenced
  by the new wait_for).

- **tui**: Allow text selection + copy (stop overriding ctrl+c)
  ([`5d01ba7`](https://github.com/Secure-Hex/hexharness/commit/5d01ba76c412739d27c503c3bee3dd4f0b0e3314))

ctrl+c was bound to quit, stealing Textual's native copy-selection action. Removed the override so
  drag-to-select + ctrl+c copies; ctrl+q still quits. Moved save + sandbox cleanup to on_unmount so
  they run on every exit path.

- **tui**: Cancel a stuck turn (Ctrl+X) and time out hung providers
  ([`0c00542`](https://github.com/Secure-Hex/hexharness/commit/0c00542ead12a06afa5a0a54db6d5b7cdccf82a6))

A hung provider (e.g. a slow custom gateway) left the turn "working…" forever; with queuing, every
  new message piled up and the operator was locked out. Add Ctrl+X to cancel the running turn, clear
  the queue, drop the unanswered trailing user message, and return to ready. Also give the
  OpenAI-compatible clients a 90s timeout and max_retries=1 so a hung gateway surfaces an error
  instead of blocking indefinitely.

- **tui**: Path(none) crash editing engagement in a blank session
  ([`c89c79a`](https://github.com/Secure-Hex/hexharness/commit/c89c79aa69969b30e6906ccd54d850123e015e8a))

Ctrl+E / Ctrl+O wrote to Path(self.engagement_path), which is None on a blank launch. Now a blank
  session derives engagements/<slug>.engagement.yaml from the engagement name, writes there, and
  rebuilds a file-backed engine (shared _activate_from_file with the draft-approval path).

- **tui**: Path(none) in ROE/scope editor when nothing is running
  ([`4e6b520`](https://github.com/Secure-Hex/hexharness/commit/4e6b52004ba7149adb003f755085ffe4a01a505b))

Ctrl+O (and Ctrl+E) before any prompt hit Engagement.load(None) because both the running engine and
  the engagement file were absent. Added _base_engagement() (running engine -> file -> unconfigured
  default, never None). When no engine exists, the editors now persist the engagement and adopt its
  path without building an engine (which would need a provider).

- **tui**: Preserve conversation across mode and provider changes
  ([`2144ac3`](https://github.com/Secure-Hex/hexharness/commit/2144ac3a19ea82a1f90dcc62e929ffe834d040ac))

Changing mode (Ctrl+O) rebuilt the engine and started an empty conversation, so the model lost all
  prior context. Now mode updates the ExecContext IN PLACE (re-clamped by ROE), keeping the engine,
  event log, evidence and conversation. Changing provider rebuilds only the loop and carries the
  conversation over. _ensure_engine is idempotent (build engine if missing, loop if missing).

- **tui**: Scope editor crashed adding an entry (DuplicateIds)
  ([`5d6b1a8`](https://github.com/Secure-Hex/hexharness/commit/5d6b1a834adca15b72cebb2eab5a3faecef77f91))

ListView.clear() is async; _refresh re-added items with fixed ids ("entry-N") in the same frame
  before the old ones were removed, raising DuplicateIds on the first add/remove. Now _refresh
  awaits clear() and drops per-item ids (removal is by highlighted index, not id); the
  add/remove/on_mount handlers are async and await it. Regression test covers adding a domain.

- **tui**: Turn never ran — _running collided with Textual App internal
  ([`27f9d6a`](https://github.com/Secure-Hex/hexharness/commit/27f9d6a6638779924d98ffe383909842c0ba41be))

The queue flag was named self._running, which shadowed Textual App's own _running attribute: Textual
  sets it True while the app is running, so the queue logic thought a turn was always in flight and
  queued every message instead of running it — the model never responded and the UI looked frozen.
  Renamed the flag to _turn_running. Verified end-to-end: a submitted prompt now runs and returns.

- **vault**: Names() leaked the whole environment with an empty prefix
  ([`7fc16a9`](https://github.com/Secure-Hex/hexharness/commit/7fc16a97d40c94515950d7417a2560032484b895))

startswith('') matched every env var, so the secrets panel dumped the entire environment (names
  only, no values). Now only *_API_KEY vars (and a non-empty configured prefix) surface, plus stored
  secret names.

### Build System

- Correct repository URL to Secure-Hex/hexharness
  ([`b48b6da`](https://github.com/Secure-Hex/hexharness/commit/b48b6da852c36374482b1f1709faa402bb5e489c))

- Prepare for PyPI release
  ([`b957641`](https://github.com/Secure-Hex/hexharness/commit/b9576414324471ee20cb886b2f7a7fc5d2e687af))

- Apache-2.0 LICENSE + NOTICE (dual-use authorized-testing note); SPDX license + license-files in
  metadata - complete project metadata: readme, authors, keywords, classifiers, urls - ship data in
  the wheel (Dockerfile, ATT&CK/CWE JSON, knowledge corpus, skills, report templates) — verified
  present - gitignore build artifacts

Verified: python -m build + twine check both pass; name 'hexharness' is free on PyPI.

### Code Style

- **tui**: Dock the commands panel on the left
  ([`4a51cb4`](https://github.com/Secure-Hex/hexharness/commit/4a51cb454a64b6fa5e414391fc0ec689001862ce))

### Continuous Integration

- Release automation + test CI; start official v1.0.0
  ([`f7498d4`](https://github.com/Secure-Hex/hexharness/commit/f7498d48cffacf6bd71db1d0cfdf396f6d3849c5))

- version 1.0.0 (official release baseline) - python-semantic-release config: Conventional Commits
  drive the bump (feat->minor, fix/perf->patch, breaking->major), tag v{version}, changelog -
  .github/workflows/release.yml: on push to main, bump+tag+GitHub Release and publish to PyPI via
  Trusted Publishing (OIDC) - .github/workflows/ci.yml: run the test suite on push/PR

### Documentation

- How to write HexHarness modules (tools, skills, MCP, providers)
  ([`8943480`](https://github.com/Secure-Hex/hexharness/commit/8943480c5efcd7d7cc5b0e2b80e13abea5720080))

- Rewrite README to reflect current state
  ([`a257483`](https://github.com/Secure-Hex/hexharness/commit/a257483515fbc204ab6f2ddd6e72566e19e0457a))

TUI quickstart + full CLI (run/init/tui/build-image/verify/report), the 41-tool capability set,
  session-persistent Kali sandbox + hardware mode, full ATT&CK/CWE knowledge base + RAG corpus +
  skills, encrypted persistent vault, run_workflow, reverse-shell handler, and updated
  invariants/layout/ceilings. Test count 252.

- **skills**: Playbooks for workflow, reverse-shell, and exploitation
  ([`61eeb6d`](https://github.com/Secure-Hex/hexharness/commit/61eeb6dc9bf48d01ecc656c07162b5df71a8abc2))

The model learns tools from their descriptions (always in context); the multi-step flows need a
  deeper how-to it can pull via skill_lookup: - workflow-chaining: run_workflow step shape,
  templating, for_each, condition - reverse-shell-handler: listener -> sessions -> exec -> stop
  lifecycle - exploitation: msfvenom -> listener -> exploit_run -> shell, end to end

Made the skill-discovery tests assert a subset so new skills don't break them.

### Features

- Configurable sandbox image (default Kali) and exec_command is INTRUSIVE
  ([`d8749ce`](https://github.com/Secure-Hex/hexharness/commit/d8749ceeaa493a273f405f27cb868fad96118744))

exec_command now runs in kalilinux/kali-rolling by default (was alpine, which lacks python/tooling).
  The image is a per-engagement setting (sandbox_image), editable from the full engagement editor
  (Ctrl+E) and applied live on scope change. exec_command drops from DESTRUCTIVE to INTRUSIVE — it
  runs in a throwaway container so it can't harm the host — while keeping requires_approval (it is
  not scope-sensitive and can reach the network).

- File/exec modules, chat-driven extensibility, and TUI capability/secret UX
  ([`a49602d`](https://github.com/Secure-Hex/hexharness/commit/a49602d3169fc7032494c7ff69ec6f41fe2064b7))

Add modular capabilities, all routed through the control-plane chokepoint:

- tools/native/fs.py, exec.py: FileReadTool (ACTIVE), FileWriteTool (INTRUSIVE + approval),
  ExecCommandTool (DESTRUCTIVE + approval, sandboxed). File tools are confined to a per-engagement
  workspace with a single traversal-guard chokepoint. - tools/native/extend.py: SkillInstallTool and
  McpConnectTool let the model, by chatting, install a skill or connect an MCP server at runtime,
  mutating the live registries. mcp_connect resolves per-invocation credentials via the out-of-band
  SecretRequester (value stored in the vault, never returned or logged). - TUI: ctrl+t capability
  panel (tools/skills/secret-names/provider, values never shown), a masked SecretModal, and a
  TUISecretRequester wired into the engine. - CLI run/init use GetpassSecretRequester;
  default_registry wires all of the above with a per-engagement workspace and the shared
  vault/secret-requester.

- Persistent vault, OSINT, parallel scan, exploitation modules
  ([`e9c11f8`](https://github.com/Secure-Hex/hexharness/commit/e9c11f807df0042ba35dd25f36039b3c3f67a35a))

- vault (#2): optional encrypted-at-rest persistence (Fernet) per engagement at
  .hexharness/<slug>/vault.enc; degrades to in-memory without cryptography. Secrets pasted once
  survive restart; values never reach the model. [secrets] extra. - osint (#6): wayback_urls
  (PASSIVE, scope), github_dork (PASSIVE, GITHUB_TOKEN via vault), cloud_storage_enum (ACTIVE +
  approval). Stdlib-only, injectable fetch. - parallel_scan (#8): concurrent multi-host nmap, scope
  enforced INTERNALLY fail-closed, INTRUSIVE + approval, bounded concurrency. - exploit (#5):
  msfvenom_payload + exploit_run, both DESTRUCTIVE + approval, exploit_run scope-checked; sandboxed.
  C2/revshell listener deferred.

Wired into default_registry; 243 passed.

- Scaffold HexHarness agentic pentesting harness
  ([`5000661`](https://github.com/Secure-Hex/hexharness/commit/500066159f124222a5c9203bdd5ca89d7cd96cce))

Introduce the full engine across all nine build phases. The core value is a domain control plane
  (scope, ROE, evidence, approvals, budget) that is unbreakable by design, not the agent loop.

Non-negotiable invariants, each with tests: - agent loop never calls tool.run() directly; always
  ControlPlane.authorize() - authorize order scope_guard -> mode.decide(risk) -> roe.cap(decision),
  fail-closed - Scope Guard is a hard gate no mode (not even bypass) can skip - ROE sets an
  immutable ceiling; active mode = min(requested, ceiling) - findings enter CANDIDATE; only
  CONFIRMED reach the report - kill switch is out-of-band (signal / trigger file) and checkpoints
  before killing

Layers: normalized LLM providers (Anthropic/OpenAI/Google/Ollama + router), single-agent loop and
  orchestrator-worker subagents, append-only hash-chained event backbone, tool registry + native
  tools + MCP + hardened Docker sandbox, evidence store, client/daemon JSON-RPC split with session
  attach/resume, OTel projection + snapshot/replay recovery, skill engine, knowledge layer (MITRE
  ATT&CK + TF-IDF RAG), and templated reporting.

Optional integrations are lazy-imported; core and tests run with none installed. 68 passed, 6
  skipped.

- **agent**: Persistent conversation + context-window compaction
  ([`3131089`](https://github.com/Secure-Hex/hexharness/commit/313108973d8cb4b4a56a89c4144fec496b4447c9))

Make the agent loop keep a persistent conversation across run() calls (the model now remembers prior
  turns), track last_input_tokens from each response, and know each model's context window
  (context_window.py, per-prefix table). Add compact(): summarize the history into durable notes and
  replace it with one summary message. Auto-compacts before a turn when the last call crossed ~80%
  of the window; also callable manually. Emits CONTEXT_COMPACTED. Exposes context_ratio() for a UI
  gauge.

- **agent**: Put the engagement scope, ROE and mode in the model's context
  ([`23df590`](https://github.com/Secure-Hex/hexharness/commit/23df590869bf99ef61b4b104eb932cd0444fe1c8))

The loop now prepends a live "Engagement boundary" section to the system prompt — in-scope
  domains/CIDRs, exclusions, the ROE ceiling (max_risk/autonomy/phase) and the current mode —
  rebuilt each turn so scope/ROE edits are reflected immediately. The model knows where it may act
  instead of wasting turns on auto-denied targets.

- **agent**: Tell the model exec_command containers are ephemeral
  ([`6538fd9`](https://github.com/Secure-Hex/hexharness/commit/6538fd9aa43571e326b8d012f5996b783f431f46))

Each exec_command is a fresh docker run --rm; installs don't persist across calls, only /workspace
  does. Added guidance to the default system prompt so the model installs-and-uses within one call
  (sh -c) or writes to /workspace, and uses the browser tool (host Playwright) instead of installing
  it in the sandbox.

- **c2**: Reverse-shell handler — listener, sessions, exec, scope-gated
  ([`e4cbe58`](https://github.com/Secure-Hex/hexharness/commit/e4cbe58a1a4447adb9b334b40a7d064901e131e8))

Long-lived TCP listener (ReverseShellManager, one per engine) catches reverse shells and lets the
  agent interact: - listener_start (DESTRUCTIVE + approval): bind LPORT, wait for a callback -
  shell_sessions (PASSIVE): list caught shells + dropped out-of-scope peers - shell_exec
  (DESTRUCTIVE + approval): run a command in a caught shell - listener_stop: close one session or
  tear down everything

Safety: a connection whose peer IP is out of engagement scope is dropped on connect (fail-closed,
  recorded for audit). Listeners/sessions are torn down on exit via Engine.close_sandbox. Verified
  with a loopback fake-shell round-trip.

- **control**: Add a BYPASS phase that lifts the phase ceiling
  ([`815c792`](https://github.com/Secure-Hex/hexharness/commit/815c792b910cadc955dcdd53e1a2f811c64725e0))

Phase.BYPASS runs any tool regardless of phase (ceiling = DESTRUCTIVE), so the agent can act across
  recon/exploitation/reporting without the per-phase gate. ROE max_risk and the Scope Guard still
  bind — bypass lifts only the phase restriction, not the hard gates. Available in the CLI --phase
  and the TUI mode menu.

- **control**: Bypass autonomy skips the requires_approval HITL prompt
  ([`bc10c77`](https://github.com/Secure-Hex/hexharness/commit/bc10c774713e7086b37f824447e540e08dd01396))

In bypass the operator explicitly chose to run without asking, so a requires_approval tool
  (exec_command, smb_enum, file_write, ...) no longer prompts for HITL — provided the ROE permits
  bypass autonomy (the mode is clamped to max_autonomy). Scope Guard and the ROE max_risk ceiling
  still bind, so nothing out of scope or over the risk cap runs. Non-bypass modes prompt as before.

- **control**: Human-approved runtime scope changes
  ([`5ca7364`](https://github.com/Secure-Hex/hexharness/commit/5ca7364dc67be48d213f4433c1eb4e17289ddde1))

The model can now PROPOSE an engagement/scope change from chat: engagement_draft emits
  ENGAGEMENT_PROPOSED (and is registered in the default toolset). Applying it is
  Engine.apply_engagement — the ONLY sanctioned runtime scope/ROE swap, invoked solely by explicit
  human approval, never by a tool or the model. It replaces scope_guard + ROE in place (keeping the
  event log, evidence, budget spend, and conversation), re-clamps the context mode to the new ROE,
  and audits SCOPE_CHANGED. Because activation lives outside the control plane's mode logic, no mode
  (not even bypass) can bypass the human approval. TUI wiring follows.

- **control**: Out-of-band secret flow for tools that need credentials
  ([`c54bd79`](https://github.com/Secure-Hex/hexharness/commit/c54bd79934a74a6a5fd4c07fff48273e5a443342))

Tools can declare required_secrets. The control plane resolves them after the HITL gate: a missing
  secret is requested from a SecretRequester channel that is separate from the agent/model loop, the
  operator supplies the value, and it goes straight into the Vault. The value never reaches the
  model, a tool_result, or an event payload — only the secret's name is audited (SECRET_PROVIDED).
  Cancelling the prompt denies the action (fail-closed). The Vault gains in-process set/names and
  the engine wires one shared vault into the control plane and tools.

- **engagement**: Draft engagements from a natural-language brief
  ([`6df30d0`](https://github.com/Secure-Hex/hexharness/commit/6df30d0c6e2ef91150d66f7aa3e5be8e5ec21b20))

Add an engagement_draft tool and a `hexharness init` CLI flow: the operator describes scope/ROE in
  natural language, the agent drafts a validated engagement.yaml, and the operator confirms before
  any session runs under it.

The model can never grant itself scope or ROE at runtime (invariants #3/#4): drafting only writes an
  inert file, activation is a human-confirmed step, and the bootstrap engine used for drafting has
  empty scope and report-only autonomy so it can draft but cannot scan or exploit. The spec is
  validated by building the real Scope Guard and ROE from it, so a bad CIDR or unknown enum fails
  before any file is written.

Engine assembly is refactored into a shared _assemble() used by both from_engagement() and the new
  bootstrap().

- **evidence**: Add reproduction/PoC field to findings and record_finding
  ([`8af334b`](https://github.com/Secure-Hex/hexharness/commit/8af334b2c18e2726ecf591f4686ace1e769edf57))

- **evidence**: Record_finding tool so the agent can log findings
  ([`a2b1fdf`](https://github.com/Secure-Hex/hexharness/commit/a2b1fdf41b48b8c6b4c9a227ee6d1f1c2708bfa7))

Add a record_finding tool that writes a finding into the evidence store as a CANDIDATE (invariant #5
  — only human curation promotes it to the report; the model can never write a confirmed finding).
  PASSIVE, not scope-sensitive. Wired into default_registry when an evidence store is present (the
  engine passes its own). Closes the gap where nothing in the agent loop could create findings.

- **knowledge**: Cwe_lookup covers the full MITRE CWE catalog
  ([`795fd9b`](https://github.com/Secure-Hex/hexharness/commit/795fd9ba1f904371df56077004c717b75e47e76e))

Hardcoded 40-entry table missed most CWEs (602, 603, ...). Now loads the full catalog from a bundled
  compact JSON (id -> [name, description]) generated from cwec_latest.xml — 969 weaknesses. Loader
  mirrors the ATT&CK one; the missing-id message no longer dumps every id.

- **knowledge**: Full ATT&CK, CWE top-40, and in-KB tool/workflow docs
  ([`9c61903`](https://github.com/Secure-Hex/hexharness/commit/9c619036dba134e8a76f15d3c046bc57c2f99fe3))

The agent searches the knowledge base for how-to, so put it there: - corpus: workflow_chaining.md
  (run_workflow usage) + a capability reference split by category
  (tools_recon/osint/exploitation/analysis/evidence_reporting/ meta) with per-tool
  risk/approval/scope/inputs/usage + new playbooks (web_xss, web_ssrf, api_testing). 4 -> 14 corpus
  docs. - mitre_attack_lookup: 20 -> 697 techniques (official enterprise STIX, compact 4-key shape;
  loader unchanged). - cwe_lookup: 6 -> 40 (CWE Top 25 2023 + common web/app). - package-data ships
  knowledge/corpus. 251 passed.

- **providers**: Openai-compatible gateways + bring-your-own provider
  ([`ac7d2f9`](https://github.com/Secure-Hex/hexharness/commit/ac7d2f99f37fb6ad7fe0e5893acce988076d5602))

Add a generic OpenAICompatibleProvider that points the OpenAI adapter at any base_url, and register
  the common gateways in the TUI catalog with verified endpoints: OpenRouter, Groq, Together,
  DeepSeek, xAI, Mistral, Fireworks, Perplexity. They appear in the provider list and reuse the
  existing key-register flow. build_custom() lets an operator supply their own base_url + key +
  model at runtime for any OpenAI-compatible endpoint (self-hosted gateways, vLLM, ...).

- **providers**: Real token streaming for OpenAI-compatible providers
  ([`bf85abe`](https://github.com/Secure-Hex/hexharness/commit/bf85abec96e925cf40a72490a9bf3c46a340a7c9))

Add stream_openai: a shared Chat Completions streaming accumulator that pushes text deltas to the
  on_text sink as they arrive and folds the stream (text + tool-call argument deltas + usage) back
  into a normalized ModelResponse. Wire it into OpenAIProvider, OllamaProvider, and
  OpenAICompatibleProvider (so every gateway — OpenRouter, Groq, Together, DeepSeek, xAI, Mistral,
  Fireworks, Perplexity — and bring-your-own endpoints stream live in the TUI). Non-streaming
  remains the path when no sink is given.

- **providers**: Stream model text through an on_text sink into the TUI
  ([`83f68e9`](https://github.com/Secure-Hex/hexharness/commit/83f68e9206a17ea5d71f0ca153f68d5dcd2975b1))

Add an optional on_text callback to the LLMProvider contract and thread it through AgentLoop and
  Engine.loop. The Anthropic adapter streams real token deltas via messages.stream; FakeProvider
  emits a synthetic delta for tests; OpenAI/Google/Ollama accept the parameter and ignore it for now
  (real streaming is a TODO), and the Router forwards it to the chosen route.

The TUI renders deltas live in a dedicated line and flushes each turn's text into the transcript
  permanently when its MODEL_RESPONSE arrives, so intermediate narration before tool calls is
  preserved. Non-streaming providers fall back to writing the final return value.

- **reporting+audit**: Wire report generation and audit-log verification
  ([`e85d8b6`](https://github.com/Secure-Hex/hexharness/commit/e85d8b6cdfbaa2c75638f5255e4826612717b530))

Reporting module was dead code; now reachable three ways: - generate_report tool (PASSIVE, reads
  only confirmed findings, writes to the workspace; Engine.loop injects the provider for the LLM
  prose sections) - TUI Ctrl+G - CLI 'hexharness report --engagement X --out r.{html,pdf,docx,md}'
  build_report() orchestrates from_evidence -> fill_generative -> render.

Audit: EventStore.verify() (hash chain) exposed via 'hexharness verify', reporting OK or the tamper
  point.

Also: TUI slash registry now discovers packaged + global + project skills (was packaged-only),
  matching skill_install scopes.

- **sandbox**: Metasploit + hardware access (USB/UART, WiFi) for exec
  ([`7aa298f`](https://github.com/Secure-Hex/hexharness/commit/7aa298f6dc93e59797b3efebbf79ea92b1ce95ee))

- Dockerfile: add metasploit-framework, aircrack-ng, iw/wireless-tools/rfkill (wifi),
  usbutils/pciutils (device discovery), minicom/screen/python3-serial (USB-UART). -
  engagement.hardware_access (default False): when set, the exec_command session container gets host
  USB passthrough (-v /dev/bus/usb, -v /dev), host net (so wireless NICs are visible), and
  --privileged (monitor mode/rfkill/raw ioctls). Drops sandbox isolation — opt-in only. Plumbed
  engagement -> ExecCommandTool -> exec_in_session; apply_engagement updates it live.

- **sandbox**: Mount the engagement workspace into exec_command
  ([`e1121de`](https://github.com/Secure-Hex/hexharness/commit/e1121de034367ca2eb7ea68284469d182e26a558))

SandboxExecutor can mount a host workspace dir read-write at /workspace (cwd set there);
  exec_command uses the per-engagement workspace, so files it creates persist on the host and are
  shared with file_read/file_write (previously they vanished with the --rm container). The dir is
  chmod 0777 before mounting so a rootless/userns Docker (where container-root maps to an
  unprivileged host uid) can still write.

- **sandbox**: One long-lived exec_command container per session
  ([`ab4079b`](https://github.com/Secure-Hex/hexharness/commit/ab4079bcdf38a1cde6a4747092f2e9ea917ad5f4))

exec_command now execs into a single detached container (docker run -d + docker exec) started on
  first use, so pip/apt installs and other state persist across calls within a session. Only the
  host-mounted /workspace survives after close_session() removes it (wired into TUI quit + CLI
  finally + atexit; stale-name rm -f on start recovers from hard kills). Scanners keep ephemeral
  run() for per-call caps (NET_RAW).

Also drop a stray i-have-adhd skill mistakenly installed into the library.

- **sandbox**: Packaged Kali image + full-capability exec_command
  ([`afb7071`](https://github.com/Secure-Hex/hexharness/commit/afb7071150f2e547f919d7cc70cf3f6481107104))

- ship Dockerfile (Kali + tools) in the wheel via package-data; build on demand or via 'python -m
  hexharness build-image' - exec_command runs with default Docker caps (drop_caps=False) and bridge
  network so apt-get/dpkg and any command work; scanners keep cap-drop ALL

- **skills**: /slash skill references in the TUI prompt
  ([`0481585`](https://github.com/Secure-Hex/hexharness/commit/048158589594c5b7d1badf527cbe7558709bc932))

Add Claude-Code-style slash references: type "/<skill> <task>" and the skill's playbook is pulled
  into the prompt so the model follows it for that task; "/" (or /help) lists the available skills;
  an unknown "/name" is reported with the list instead of being run. Previously skills were only
  reachable indirectly via the skill_lookup tool at the model's discretion — now the operator can
  invoke one directly. Resolution uses the bundled SkillRegistry; expansion logic is unit-tested.

- **skills**: Skill_install asks project vs global scope
  ([`762f6da`](https://github.com/Secure-Hex/hexharness/commit/762f6da02998c80068e07397f83d1482833aadf9))

skill_install now requires a scope: 'project' (.hexharness/<slug>/skills, this engagement only) or
  'global' (~/.hexharness/skills, every engagement). The tool description tells the model to ask the
  operator which they want. Skill discovery is layered — packaged < global < project (later
  overrides) — and tolerates missing dirs.

- **tools**: Browser module (Playwright) — interact + screenshots
  ([`0158ec5`](https://github.com/Secure-Hex/hexharness/commit/0158ec530dc956f41dcb826242e1eb9cf28de240))

Add a scope-sensitive `browser` tool driving headless Chromium via Playwright: open a URL, run
  interaction steps (goto/click/fill/press/text/wait/screenshot), read page text, and save full-page
  screenshots to the engagement workspace (on the host, so the operator can open them). The Scope
  Guard checks the URL host. The browser session is injectable for tests (no real browser needed);
  Playwright is an optional [browser] dep (needs `playwright install chromium`).

- **tools**: List_findings — agent reads back its recorded findings
  ([`2bafa2d`](https://github.com/Secure-Hex/hexharness/commit/2bafa2d1c43eec5df4e09306e448adc87b62b325))

Pairs with record_finding (write-only until now). PASSIVE, no scope/approval. Filters by status
  (all|candidate|confirmed|rejected), sorts by severity, and detail=true includes
  description/reproduction/evidence. Lets the model avoid duplicate findings and see what it has
  before generating a report.

- **tools**: Native DNS/WHOIS, raw-socket nmap, free-form nmap flags
  ([`4bc3de0`](https://github.com/Secure-Hex/hexharness/commit/4bc3de09180637da2d2c427add95abd3315cb0cd))

Recon no longer depends on a tooled sandbox image (bare kali lacks dig/whois/dnsutils): - dns_enum
  uses dnspython natively (no sandbox); whois_lookup does raw WHOIS over TCP/43 with IANA referral
  (stdlib). smb_enum stays sandboxed (needs smbclient) with a clearer "image lacks smbclient" hint.
  - port_scan: accept arbitrary nmap `flags` (SYN/-sV/-A/-O/NSE) and enable raw sockets —
  SandboxExecutor gains cap_add so a tool can request NET_RAW while still dropping all other caps;
  nmap defaults to -sS -Pn. argv stays a list (no shell injection); host is still scope-checked.

- **tools**: Network service, recon, and binary/reversing modules
  ([`0d6be50`](https://github.com/Secure-Hex/hexharness/commit/0d6be509b77313bfb7e49ab450181fdbd244b644))

Expand beyond web pentesting with 10 new tools, all gated by the control plane: - services.py
  (ACTIVE, scope-sensitive): banner_grab, ftp_check, ssh_info, http_probe - recon.py (kali sandbox,
  scope-sensitive): dns_enum, smb_enum (INTRUSIVE+approval), whois_lookup - binary.py (host static
  analysis, workspace-confined, never executes the target): binary_info, checksec, disassemble
  Network tools are scope-sensitive (unlike exec_command), so the Scope Guard validates the target
  host/url. Backends are injectable for tests (no net/docker). Wired into default_registry — 25
  tools total.

- **tools**: Postman collection module (list + scope-checked run)
  ([`c117334`](https://github.com/Secure-Hex/hexharness/commit/c1173344648e51eb3ab96e2117f74b704e9ce7f3))

Add postman_list (PASSIVE: parse a Postman v2.1 collection, recursing folders, and list its
  requests) and postman_run (INTRUSIVE + approval: execute one named request). The collection
  supplies method/path/headers/body but the host comes from a scope-checked base_url, so a
  collection can never target an out-of-scope host. Stdlib HTTP, no newman dependency; Postman cloud
  fetch (POSTMAN_API_KEY) is a noted follow-on.

- **tools**: Shodan_host — real tool that exercises the out-of-band secret flow
  ([`1a0f05f`](https://github.com/Secure-Hex/hexharness/commit/1a0f05f2f6e2d63d93255bf1ef21ca591dbc0770))

Add shodan_host (ACTIVE, scope-sensitive) which declares required_secrets= ["SHODAN_API_KEY"]. The
  first run triggers the control plane's out-of-band secret prompt: the operator supplies the key
  (masked, never shown to the model), it is stored in the vault, only its NAME is audited
  (SECRET_PROVIDED), and the tool uses it. Gives a concrete way to test the secret mechanism end to
  end; cancelling the prompt denies with gate "secrets".

- **tools**: Web_search module with pluggable backends
  ([`fb5cd75`](https://github.com/Secure-Hex/hexharness/commit/fb5cd7594da4d43cf3ff0e8d6df9fd4dbacb5b93))

Add a web_search OSINT tool: free DuckDuckGo (ddgs) by default — no key — and, if a Tavily or Exa
  API key is present in the vault/env, that cleaner backend is used instead (tavily > exa >
  duckduckgo). Paid keys are read from the vault, never passed by the model. ACTIVE and not
  scope-sensitive (OSINT, not an engagement target); Tavily/Exa use stdlib HTTP so only the free
  backend adds a dep ([search]).

- **tui**: Approve model-proposed scope changes from the TUI
  ([`d289ee0`](https://github.com/Secure-Hex/hexharness/commit/d289ee08aafc374c1f330c51fa5f092c1d19014c))

Wire the runtime scope-change flow into the TUI: when the model proposes an engagement
  (ENGAGEMENT_PROPOSED), a ScopeApprovalModal shows the new scope + ROE and asks the operator;
  approving calls engine.apply_engagement (and the live loop adopts the re-clamped context),
  rejecting leaves scope untouched. SCOPE_CHANGED is logged. The modal is the sole activation path,
  so no mode — bypass included — can change scope without the human.

- **tui**: Arrow-key selection among slash suggestions
  ([`e3914a0`](https://github.com/Secure-Hex/hexharness/commit/e3914a0f4d6ded417801051e31397e74663699aa))

Up/Down move a selection through the live slash matches (the chosen one marked with ▶); Tab now
  completes the SELECTED match, not just the top one. Editing the token resets the selection to the
  top. The suggestion bar hints "↑/↓ select · Tab complete".

- **tui**: Auto-growing wrapped prompt + keep modals on-screen
  ([`3f1d7de`](https://github.com/Secure-Hex/hexharness/commit/3f1d7de69e47bb7f0eb73ce877d3b03e65ada035))

Replace the single-line prompt Input with a PromptArea (multi-line TextArea): soft-wraps and grows
  its height with the content up to a cap, so a long prompt (or live dictation, which is one
  unbroken line) stays visible instead of scrolling off to the side. Enter submits, Ctrl+J inserts a
  newline.

Fix the provider screen overflowing once the gateway list grew: its content now lives in a
  VerticalScroll with the action buttons (incl. "＋ Custom") pinned outside the scroll, and the panel
  has a definite height, so every control stays on screen at any terminal size.

- **tui**: Blank launch when no --engagement, configure by chatting
  ([`b2f9301`](https://github.com/Secure-Hex/hexharness/commit/b2f93017673bc371a6e69e2a608e78f4817d7584))

Without --engagement the TUI now starts unconfigured: empty scope, no resumed history. The model can
  only draft an engagement (everything else denied fail-closed); approving the draft rebuilds a
  file-backed engine under the new engagement's slug, carrying the conversation forward.

- Engine.blank(): empty-scope/report-only engine with the FULL registry - __main__ tui --engagement
  default None - _propose_scope rebuilds on approval when launched blank

- **tui**: Context gauge, /compact, and auto-compact notice
  ([`766b800`](https://github.com/Secure-Hex/hexharness/commit/766b80094f5d0a62606a7f07808ed971fce65eb3))

Show live context usage in the header (ctx 160k/200k · 80%) from the loop's last input-token count
  vs the model's window. Add a /compact command to summarize and shrink the conversation on demand,
  and surface CONTEXT_COMPACTED events (auto or manual) as a transcript line so the operator sees
  when and why it happened.

- **tui**: Edit the ROE ceiling from the mode menu too (Ctrl+O)
  ([`28ec199`](https://github.com/Secure-Hex/hexharness/commit/28ec19943a11b602cc2623f3f2c831c763dc68eb))

Ctrl+O now shows the ROE ceiling (max_risk/max_autonomy/max_phase) alongside the autonomy/phase
  selection, so the operator can raise the hard cap from the same place they set the mode. Applying
  persists + audits the ROE change (shared with the Ctrl+E editor via a common ROE_CHOICES). The
  requested mode is still clamped to this ceiling.

- **tui**: Edit the ROE ceiling from the scope editor (Ctrl+E)
  ([`82a830c`](https://github.com/Secure-Hex/hexharness/commit/82a830c51e0dcbb2cb9b818acf18106ba98393a9))

Ctrl+E now also edits the engagement ROE — max_risk, max_autonomy, max_phase — via selects,
  alongside scope. This is the sanctioned way to raise the ceiling so riskier tools can run: e.g.
  exec_command (DESTRUCTIVE) was denied by roe.cap when max_risk was "active" even in bypass,
  because bypass lifts HITL and the phase gate but NEVER the ROE (invariant #4). Raising max_risk to
  destructive (a deliberate human edit, persisted and audited as SCOPE_CHANGED) lets it run.

- **tui**: Enter completes the selected slash suggestion
  ([`d702a85`](https://github.com/Secure-Hex/hexharness/commit/d702a85359e7799f41610dfbc5a3c50624159941))

While typing "/<prefix>" with matches, Enter now completes the selected suggestion (same as Tab)
  instead of submitting; a non-matching "/x" still submits so unknown-skill feedback works. Hint
  updated to "Tab/Enter complete".

- **tui**: Finding detail view with PoC/reproduction (Enter/d in findings panel)
  ([`9b0fda4`](https://github.com/Secure-Hex/hexharness/commit/9b0fda4f9aefb46a4b1b203c170790ca28f963c9))

- **tui**: Findings panel with human curation (Ctrl+F)
  ([`8dad155`](https://github.com/Secure-Hex/hexharness/commit/8dad1558f7168b990e3561616dcfec65eed93774))

Add a FindingsScreen (Ctrl+F) listing security findings grouped by state with counts — candidates
  first, then confirmed, then rejected. The operator curates from the panel: c confirms / r rejects
  the highlighted candidate (invariant #5 — human promotion), calling
  evidence.confirm/reject(curator="operator") and refreshing in place. Content scrolls; action
  buttons stay pinned. Empty-state when no engagement is running yet.

- **tui**: Full engagement editor (Ctrl+E)
  ([`f033fdd`](https://github.com/Secure-Hex/hexharness/commit/f033fdd7fe7aa9f917aa67b9048279e3f0f5cbc1))

Ctrl+E now edits EVERY engagement setting, not just scope+ROE: name, client, scope
  (domains/CIDRs/exclusions), ROE ceiling + time windows (add/remove), budget
  (max_tokens/max_usd/max_seconds), and report_template. Apply builds a complete engagement,
  validates it (bad CIDR / number / HH:MM window is rejected with nothing persisted), writes it to
  the engagement file, and applies it live via apply_engagement (audited SCOPE_CHANGED).
  ScopeEditScreen -> EngagementEditScreen.

- **tui**: Hardware_access toggle in the engagement editor (Ctrl+E)
  ([`b3e0313`](https://github.com/Secure-Hex/hexharness/commit/b3e0313427299d8be21cfb2b1afca85149f6072b))

Checkbox in the Sandbox section; applies through the existing edit path (writes the engagement,
  re-clamps live). Labeled that it drops sandbox isolation.

- **tui**: Keep reasoning in the transcript and render model output as Markdown
  ([`dc1d1a1`](https://github.com/Secure-Hex/hexharness/commit/dc1d1a1bd8e97b2d7e99a973b9aa16f4f77ba6cc))

- **tui**: Live dictation — prompt fills as you speak
  ([`5f3d9c1`](https://github.com/Secure-Hex/hexharness/commit/5f3d9c19f92304a4eeaed3ef4c628e6fd9fbec57))

Dictation now streams partials: while recording, it re-transcribes the audio so far every ~1.2s and
  pushes the growing text straight into the prompt, so it fills live as the operator speaks
  (matching Claude Code) instead of only appearing after stop. Still local Whisper, off the event
  loop. Partials append to whatever was already typed; the final pass replaces them on stop.

- **tui**: Live model thinking pane + working/thinking/ready status
  ([`1a084ad`](https://github.com/Secure-Hex/hexharness/commit/1a084ad4420d725d40d0409d051001bb4d940a18))

Show the model's reasoning live (dim pane above the answer, fed by the on_thinking sink for
  reasoning-capable providers) and a status line that tracks the run lifecycle: "working…",
  "thinking…", "running <tool>…", and "ready — type a prompt" when idle. So the operator can see
  when the system is thinking, working, or waiting for the next prompt.

- **tui**: Live skill autocomplete while typing a slash command
  ([`6857e0d`](https://github.com/Secure-Hex/hexharness/commit/6857e0d724072bc3b060e8197bbdd39eeb84dc76))

As the operator types "/<prefix>" (before the first space), a suggestion bar above the prompt lists
  the matching skills (and the built-in /compact), filtered live by the prefix; it hides once a
  space is typed or the slash is cleared. Makes slash skill references discoverable instead of
  needing to remember exact names.

- **tui**: Local push-to-talk dictation (Ctrl+R)
  ([`3effe9f`](https://github.com/Secure-Hex/hexharness/commit/3effe9f0fdf416eb04349c7f2d4aae9208a76d2d))

Add Ctrl+R voice dictation in the TUI: press to start recording the mic, press again to stop,
  transcribe, and insert the text into the prompt. Transcription is LOCAL via faster-whisper so
  audio never leaves the machine (no egress during an engagement). Toggle rather than hold, since
  terminals don't reliably report key-release. Whisper runs off the event loop so the UI never
  freezes. The recorder and transcriber are injectable for testing; sounddevice/faster-whisper are
  an optional [voice] dep and the feature degrades to a hint when absent.

- **tui**: Manual scope editor panel (Ctrl+E)
  ([`9d164e3`](https://github.com/Secure-Hex/hexharness/commit/9d164e3a6c02545a7292a0f1e20a7b217a3c1aa2))

Add a ScopeEditScreen (Ctrl+E) to edit the engagement scope directly — add/remove domains, CIDRs and
  exclusions — without talking to the model. Apply validates (bad CIDR is rejected with an error,
  nothing changed), persists the new scope to the engagement file, and applies it live via
  engine.apply_engagement when a session is running (audited as SCOPE_CHANGED). The binding is
  priority so it wins over TextArea's own ctrl+e.

- **tui**: Mode menu (ctrl+o) and custom OpenAI-compatible provider modal
  ([`7053725`](https://github.com/Secure-Hex/hexharness/commit/7053725e65c40d27d2887936025e0ffcc47d0a9f))

Add a ModeScreen reachable by ctrl+o to pick autonomy/phase from a menu (the f2/f3 cycling was easy
  to miss); choosing a mode rebuilds the engine. Add a "Custom (OpenAI-compatible)" button in the
  provider screen opening a modal for name/base_url/model and a masked api key, so any
  OpenAI-compatible endpoint can be used at runtime. The key stays in the in-memory selection and
  never reaches env, logs, or the model.

- **tui**: Move shortcuts into a toggleable commands side panel (Ctrl+B)
  ([`c8ef3b3`](https://github.com/Secure-Hex/hexharness/commit/c8ef3b3e1a5f1087574a16858e26bb54c71e0e78))

The footer overflowed as bindings grew. Now the footer shows only the Ctrl+B toggle; the full
  command list (keybinds + prompt/slash commands) lives in a right-docked side panel you show/hide
  with Ctrl+B. All other bindings are show=False so the footer stays on one line at any width.

- **tui**: Opencode-style Textual UI with in-app provider management
  ([`b5f9720`](https://github.com/Secure-Hex/hexharness/commit/b5f9720eb9ebf51e110f2fd466bfb9301deba2d7))

Add a terminal UI (hexharness/tui/, python -m hexharness tui) over the engine: a live transcript
  that streams control-plane events color-coded (allow/deny/ask, tool start/finish, findings, budget
  in the header), a bordered prompt, and a footer of keybinds. Dark OpenCode-like theme with a
  swappable palette.

Providers are selected and registered from inside the TUI (ctrl+p): a badged catalog shows which
  providers have credentials configured, a model override can be typed, keys/base-url are registered
  in-process, and several providers can be combined into a cost-fallback Router. HITL approvals
  surface as a modal; the kill switch is a keybind.

Wire a `tui` subcommand into the CLI and a [tui] optional dep (textual). textual is imported only
  inside the tui package, so the core still runs without it.

- **tui**: Persist and resume HexHarness sessions
  ([`7bea875`](https://github.com/Secure-Hex/hexharness/commit/7bea8753ae916222ba8e1c165bd4e7e462c278f6))

The TUI ran entirely in-memory, so closing it lost the conversation, findings and event log. Now
  each engagement gets a file-backed session under .hexharness/<slug>/: session.sqlite holds the
  event log (hash chain) and the findings (both stores share the file), and conversation.json holds
  the agent conversation. The conversation auto-saves after every turn, on /save, and on quit;
  reopening the same engagement resumes it — events and findings are already there, the conversation
  reloads, and token spend is re-derived from the log via Recovery. Verified end-to-end: events,
  findings and conversation all restore.

- **tui**: Persist autonomy/phase across sessions
  ([`a3e81f1`](https://github.com/Secure-Hex/hexharness/commit/a3e81f194ef2a3a1b62b078fac98aa7a548552ad))

- **tui**: Persist custom providers globally with their API key
  ([`4399a71`](https://github.com/Secure-Hex/hexharness/commit/4399a716dbf1bff498c70fe9e7869f60d8064b61))

Custom (bring-your-own) providers now save to a dedicated global file,
  ~/.local/share/hexharness/providers.json ($XDG_DATA_HOME / $HEXHARNESS_PROVIDERS), chmod 0600,
  storing {name, base_url, model, api_key}. Keys are intentionally persisted so a saved provider
  reloads fully usable without re-entry (OpenCode/ aider-style) — this is separate from config.json,
  which stays non-secret and holds only the selection. Saved providers appear in the provider list
  as "custom:<slug>" entries and build directly from the stored key; no env var.

- **tui**: Queue messages typed while a turn is running
  ([`6036af7`](https://github.com/Secure-Hex/hexharness/commit/6036af7014953a778966574b94812086ce353c08))

The prompt is no longer disabled during a turn. Submitting while a run is in flight queues the
  message (shown as "⏳ queued (N)") and the queue drains one at a time as each turn finishes, so the
  operator can line up follow-ups without waiting. The status line shows how many are queued.

- **tui**: Re-render saved conversation history on resume
  ([`73caf8e`](https://github.com/Secure-Hex/hexharness/commit/73caf8ea730cd2269bf5c0a3a268d2869444b00c))

On resume the transcript was blank, so even though the model got the conversation as context it
  looked like nothing was remembered. Now the saved conversation is loaded at launch and re-painted
  into the transcript (user prompts, assistant answers as Markdown, tool calls/results dimmed), with
  a clear "end of history" marker. (Old sessions whose turns hung under the _running bug never saved
  a conversation; with that fixed, turns complete and the history persists.)

- **tui**: Remember the chosen provider across sessions
  ([`c43b754`](https://github.com/Secure-Hex/hexharness/commit/c43b754b52dac0d673f2fea84226aa16243188aa))

Persist the selected provider (kind/keys/model) to ~/.config/hexharness/config.json and reload it on
  startup, so a provider picked for a pentest is the default next session. API keys are never
  written — a custom provider's base_url/name/model persist but its key is re-entered. Config
  read/write failures are swallowed so they never break the UI; HEXHARNESS_CONFIG overrides the
  path.

- **tui**: Show active web_search backend in the capabilities panel
  ([`aceb3bb`](https://github.com/Secure-Hex/hexharness/commit/aceb3bb74fbed44e792a87de90f7903dbe043912))

Add WebSearchTool.active_backend() and a "Web search" section in the capabilities screen (ctrl+t)
  showing which backend a search would use right now — duckduckgo (free, no key) or tavily/exa (via
  API key) — so the operator can see at a glance whether queries go through the free or a paid
  backend.

- **tui**: Show tool output under each finished tool call
  ([`33e6c9a`](https://github.com/Secure-Hex/hexharness/commit/33e6c9a77267271a1a521b14fa4df2959e621530))

TOOL_FINISHED now carries a truncated copy of the tool's output (full output still reaches the
  model); the TUI renders it beneath the check mark. Also point the pentest-secure-hex engagement at
  the tooled hexharness/kali image.

- **tui**: Tab-complete a slash skill to the top match
  ([`be676f3`](https://github.com/Secure-Hex/hexharness/commit/be676f38605b2f094ceaa78d01c5d7f12d00d61b))

Pressing Tab while typing "/<prefix>" (before a space) completes it to the top matching skill (or
  /compact) and adds a trailing space. The suggestion bar now hints "Tab to complete". Completion
  and the live suggestions share one matcher so they always agree.

- **workflow**: Run_workflow — declarative multi-step tool pipeline
  ([`9c9ab9f`](https://github.com/Secure-Hex/hexharness/commit/9c9ab9f0137b6ade92e35955a728a24d66e5b5fb))

Steps are {tool, input, output?, for_each?, condition?}: {{var}} templating, output binding reused
  by later steps, for_each over a value (per-item {{item}}), condition skipping
  (==/!=/contains/truthiness), stop-on-first-failure.

Critically, each step is routed through the SAME ControlPlane.authorize() chokepoint as a direct
  tool call (Engine.loop injects a step_runner wrapping AgentLoop._handle_tool_use) — so
  scope/ROE/HITL apply per step. Verified: an out-of-scope step is denied by scope_guard and halts
  the pipeline.

Pure engine in agent/workflow.py (unit-tested); tool in tools/native/workflow_tool.py.
