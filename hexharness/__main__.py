"""Thin CLI.

    # run a task against an existing engagement
    python -m hexharness run "Look up CWE-79" --engagement engagements/example.engagement.yaml

    # describe scope in natural language; the agent drafts the engagement, you confirm,
    # then it runs the first task under it — all in one flow
    python -m hexharness init "External test of acme.example and 203.0.113.0/24, \
        exclude vpn.acme.example, enumeration only, business hours" --task "Resolve www.acme.example"

`run` is the default when no subcommand is given (back-compat). The in-process entry
point; the client/daemon WS split is a separate path.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from hexharness.control.hitl import CLIApprover
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.control.secrets import GetpassSecretRequester
from hexharness.engine import Engine

_DRAFT_SYSTEM = (
    "You are setting up a new pentest engagement. Read the operator's natural-language "
    "brief and call the engagement_draft tool EXACTLY ONCE with a structured spec: "
    "scope.domains, scope.cidrs, scope.exclusions, roe.max_risk/max_autonomy/max_phase, "
    "optional time windows and budget. Infer a short engagement name. Do not invent scope "
    "the operator did not give. After drafting, briefly summarize what you proposed."
)

_PATH_RE = re.compile(r"Draft written to (\S+) \(")


def _build_mode(args) -> Mode:
    return Mode(autonomy=Autonomy[args.autonomy.upper()], phase=Phase[args.phase.upper()])


async def _run(args) -> str:
    from hexharness.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider()
    engine = Engine.from_engagement(
        args.engagement, provider=provider, requested_mode=_build_mode(args),
        approver=CLIApprover(), secret_requester=GetpassSecretRequester(), kill_trigger_file=args.kill_file,
    )
    engine.kill_switch.install_signal_handler()
    engine.kill_switch.start_file_watch()
    try:
        return await engine.loop(provider=provider, model=args.model).run(args.prompt)
    finally:
        engine.close_sandbox()  # remove the session container; /workspace persists


async def _init(args) -> str:
    from hexharness.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider()
    # Locked bootstrap engine: empty scope, report-only, can ONLY draft an engagement.
    boot = Engine.bootstrap(out_dir=args.out, approver=CLIApprover())
    out = await boot.loop(provider=provider, model=args.model).run(args.brief)
    print(out)

    m = _PATH_RE.search(out)
    if not m:
        return "No draft was produced. Rephrase the brief and try again."
    path = Path(m.group(1))

    # HUMAN gate: the operator approves the ROE before anything runs under it (invariant #4).
    print("\n" + "=" * 60)
    print(path.read_text())
    print("=" * 60)
    try:
        answer = input(f"Activate {path.name} and run under it? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        return f"Not activated. Draft left inert at {path}."

    if not args.task:
        return f"Activated: {path}. Run a task with:\n  python -m hexharness run \"<task>\" --engagement {path}"

    engine = Engine.from_engagement(
        path, provider=provider, requested_mode=_build_mode(args),
        approver=CLIApprover(), secret_requester=GetpassSecretRequester(), kill_trigger_file=args.kill_file,
    )
    engine.kill_switch.install_signal_handler()
    engine.kill_switch.start_file_watch()
    return await engine.loop(provider=provider, model=args.model).run(args.task)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hexharness")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _common(sp):
        sp.add_argument("--autonomy", default="interactive", choices=[a.name.lower() for a in Autonomy])
        sp.add_argument("--phase", default="recon", choices=[ph.name.lower() for ph in Phase])
        sp.add_argument("--model", default=None)
        sp.add_argument("--kill-file", default=None,
                        help="touch this path from anywhere to trigger the out-of-band kill switch")

    r = sub.add_parser("run", help="run a task against an existing engagement")
    r.add_argument("prompt")
    r.add_argument("--engagement", default="engagements/example.engagement.yaml")
    _common(r)

    i = sub.add_parser("init", help="draft a new engagement from a natural-language brief, then run it")
    i.add_argument("brief", help="natural-language scope/ROE description")
    i.add_argument("--task", default=None, help="first task to run once the engagement is activated")
    i.add_argument("--out", default="engagements", help="directory to write the engagement file into")
    _common(i)

    t = sub.add_parser("tui", help="launch the terminal UI")
    # No default: launched without --engagement, the TUI starts blank (no scope, no resumed
    # history) and the operator configures a new engagement by describing the target.
    t.add_argument("--engagement", default=None)

    sub.add_parser("build-image", help="build the HexHarness sandbox image (Kali + tools)")

    v = sub.add_parser("verify", help="verify a session's audit log (SHA-256 hash chain) for tampering")
    v.add_argument("--engagement", default="engagements/example.engagement.yaml")

    rp = sub.add_parser("report", help="render a client report from an engagement's confirmed findings")
    rp.add_argument("--engagement", default="engagements/example.engagement.yaml")
    rp.add_argument("--out", default=None, help="output path; extension picks the format (.html/.pdf/.docx/.md)")
    rp.add_argument("--template", default=None, help="template path (defaults to the bundled HTML template)")
    rp.add_argument("--no-generative", action="store_true", help="skip the LLM exec-summary/risk-narrative")
    rp.add_argument("--model", default=None)
    return p


def _verify(args) -> str:
    from hexharness import session as sess
    from hexharness.engagement import Engagement
    from hexharness.events.store import EventStore, HashChainError

    name = Engagement.load(args.engagement).name
    db = sess.db_path(name)
    if not db.exists():
        return f"no session log for '{name}' at {db} — nothing to verify."
    store = EventStore(str(db))
    n = len(store.all())
    try:
        store.verify()
    except HashChainError as exc:
        return f"TAMPERED: audit log for '{name}' failed verification at — {exc} ({n} events)"
    return f"OK: audit log for '{name}' is intact — {n} events, hash chain verified."


async def _report(args) -> str:
    from hexharness import session as sess
    from hexharness.engagement import Engagement
    from hexharness.evidence.store import EvidenceStore
    from hexharness.events.store import EventStore
    from hexharness.reporting.build import build_report

    eng = Engagement.load(args.engagement)
    db = sess.db_path(eng.name)
    if not db.exists():
        return f"no session for '{eng.name}' at {db} — run a task first so there are findings."
    events = EventStore(str(db))
    evidence = EvidenceStore(str(db), events=events)
    provider = None
    if not args.no_generative:
        from hexharness.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider()
    out = args.out or str(sess.session_dir(eng.name) / f"report-{eng.name}.html")
    path = await build_report(eng, evidence, out, provider=provider,
                              template=args.template, model_name=args.model)
    return f"report written to {path} ({len(evidence.confirmed())} confirmed findings)."


def main() -> int:
    argv = sys.argv[1:]
    _subcommands = ("run", "init", "tui", "build-image", "verify", "report", "-h", "--help")
    if argv and argv[0] not in _subcommands:
        argv = ["run", *argv]  # back-compat: bare prompt => run
    args = _parser().parse_args(argv)

    if args.cmd == "verify":
        print(_verify(args))
        return 0

    if args.cmd == "build-image":
        from hexharness.sandbox.image import DEFAULT_SANDBOX_IMAGE, build_image

        ok, out = asyncio.run(build_image(DEFAULT_SANDBOX_IMAGE, on_output=print))
        print(f"\n{'built' if ok else 'failed'}: {DEFAULT_SANDBOX_IMAGE}")
        return 0 if ok else 1

    if args.cmd == "tui":
        from hexharness.tui.app import HexTUI  # textual only imported here

        HexTUI(engagement=args.engagement).run()
        return 0

    coro = {"init": _init, "report": _report}.get(args.cmd, _run)(args)
    try:
        print(asyncio.run(coro))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
