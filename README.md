# HexHarness

Agentic pentesting harness. The differentiator is not the agent loop (that is standard)
but a **domain control plane** — scope, ROE, evidence, approvals, budget — that is
unbreakable by design. Dual-use by nature; what keeps it on the right side is that the
Scope Guard + ROE are hard gates and everything lands in the hash-chained audit log.

## Install

```bash
python -m venv venv && ./venv/bin/pip install -e '.[dev]'
./venv/bin/pytest -q          # 23 tests, one per non-negotiable invariant
```

## Run

```bash
# Offline demo needs no key (scripted provider) — see the smoke test in the project notes.
ANTHROPIC_API_KEY=sk-... ./venv/bin/python -m hexharness \
    "Look up CWE-79 and explain it" \
    --engagement engagements/example.engagement.yaml \
    --autonomy interactive --phase recon
```

The requested `--autonomy/--phase` are clamped to the engagement's ROE ceiling.

### Create an engagement from a natural-language brief

```bash
ANTHROPIC_API_KEY=sk-... ./venv/bin/python -m hexharness init \
    "External test of acme.example and 203.0.113.0/24, exclude vpn.acme.example, \
     enumeration only, business hours" \
    --task "Resolve www.acme.example"
```

The agent drafts a validated `engagement.yaml` from the brief, shows it, and waits for
you to confirm before anything runs under it. The model can never grant itself scope or
ROE: drafting writes an inert file, and activation is a human step (invariants #3/#4).
The bootstrap engine used for drafting has empty scope and can only draft — it cannot scan.

## The non-negotiable invariants (each has a test)

1. The agent loop never calls `tool.run()` directly — always `ControlPlane.authorize()` first.
   (`hexharness/agent/loop.py`, `tests/test_authorize_chokepoint.py`)
2. `authorize()` order: `scope_guard → mode.decide(risk) → roe.cap(decision)`, fail-closed.
   (`hexharness/control/plane.py`)
3. Scope Guard is a hard gate no mode bypasses — not even `bypass`. Out of scope = deny.
   (`hexharness/control/scope_guard.py`, `tests/test_scope_fail_closed.py`)
4. ROE sets the engagement's max mode (immutable); active mode = `min(requested, ceiling)`.
   (`hexharness/control/roe.py`, `tests/test_roe_ceiling.py`)
5. Findings enter as CANDIDATE; only CONFIRMED reach the report; REJECTED kept with reason.
   (`hexharness/evidence/`, `tests/test_findings_states.py`)
6. Kill switch is out-of-band (signal / trigger file), works client-disconnected, checkpoints
   before killing. (`hexharness/control/kill_switch.py`)

Audit log, tracing and checkpointing are **projections** of one append-only, hash-chained
event stream (`hexharness/events/`).

## Layout

```
hexharness/
  providers/   normalized LLM types + Anthropic adapter (+ fake for tests)
  agent/       ExecContext + single-agent loop (routes every tool call through the chokepoint)
  control/     THE control plane: plane, scope_guard, policy(modes), roe, budget, hitl, kill_switch
  events/      append-only log + hash chain + bus
  tools/       Tool base (risk_level/scope_sensitive/requires_approval), registry, native tools
  sandbox/     Docker-backed executor (hardened; argv list, no shell)
  evidence/    findings (candidate/confirmed/rejected) + store
  engagement.py  engagement.yaml -> control-plane objects
  engine.py    composition root
```

## Phases — all implemented

| Phase | Where |
|---|---|
| 1 Normalized types + Anthropic + loop/chokepoint | `providers/`, `agent/` |
| 2 Event backbone (append-only + hash chain + bus) | `events/` |
| 3 Tool registry + native tools + Docker sandbox + **MCP** | `tools/`, `sandbox/`, `tools/mcp.py` |
| 4 Full control plane (scope→mode→roe→budget, HITL, kill switch, vault, USD pricing) | `control/` |
| 5 Evidence Store + findings candidate/confirmed/rejected | `evidence/` |
| 6 Client/daemon split: JSON-RPC over a transport (unix/WSS), sessions attach/resume | `protocol/`, `transport/`, `daemon/`, `client/` |
| 7 OTel span projection + snapshot/replay recovery | `observability/`, `recovery/` |
| 8 Multi-provider router (OpenAI/Google/Ollama) + orchestrator-worker subagents | `providers/router.py`, `agent/orchestrator.py`, `agent/subagents.py` |
| 9 Skill engine + knowledge (MITRE ATT&CK + TF-IDF RAG) + reporting (ReportModel + templates) | `skills/`, `knowledge/`, `reporting/` |

### Optional dependencies

Every integration is lazy-imported — core + tests run with none installed. Install per need:

```bash
./venv/bin/pip install -e '.[openai]'     # or google / otel / daemon / reporting / mcp / all
```

### Known ceilings (marked `ponytail:` in code)

- Orchestrator workers run sequentially (swap to `asyncio.gather` + per-worker providers for parallelism).
- Knowledge RAG is a linear TF-IDF scan (fine for a few local docs; add a vector index if the corpus grows).
- MCP tools default to INTRUSIVE + requires_approval unless a `classify` override says otherwise (conservative).
- `.md`→PDF and DOCX→PDF need extra converters; HTML→PDF via WeasyPrint is the primary path.
