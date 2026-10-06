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
        approver=CLIApprover(), kill_trigger_file=args.kill_file,
    )
    engine.kill_switch.install_signal_handler()
    engine.kill_switch.start_file_watch()
    return await engine.loop(provider=provider, model=args.model).run(args.prompt)


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
        approver=CLIApprover(), kill_trigger_file=args.kill_file,
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
    return p


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] not in ("run", "init", "-h", "--help"):
        argv = ["run", *argv]  # back-compat: bare prompt => run
    args = _parser().parse_args(argv)

    coro = _init(args) if args.cmd == "init" else _run(args)
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
