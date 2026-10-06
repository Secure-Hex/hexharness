"""Thin CLI. Runs one agent turn against an engagement.

    python -m hexharness "Look up CWE-79" --engagement engagements/example.engagement.yaml

Autonomy/phase default to interactive/recon and are clamped to the engagement ROE.
This is the in-process entry point; the client/daemon WS split is a later phase.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from hexharness.control.hitl import CLIApprover
from hexharness.control.policy import Autonomy, Mode, Phase
from hexharness.engine import Engine


def _build_mode(args) -> Mode:
    return Mode(autonomy=Autonomy[args.autonomy.upper()], phase=Phase[args.phase.upper()])


async def _run(args) -> str:
    from hexharness.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider()
    engine = Engine.from_engagement(
        args.engagement, provider=provider, requested_mode=_build_mode(args),
        approver=CLIApprover(), kill_trigger_file=args.kill_file,
    )
    # Arm the out-of-band kill switch: SIGUSR1 or a trigger file, both work with the
    # client/terminal detached, and both checkpoint before stopping (invariant #6).
    engine.kill_switch.install_signal_handler()
    engine.kill_switch.start_file_watch()
    return await engine.loop(provider=provider, model=args.model).run(args.prompt)


def main() -> int:
    p = argparse.ArgumentParser(prog="hexharness")
    p.add_argument("prompt")
    p.add_argument("--engagement", default="engagements/example.engagement.yaml")
    p.add_argument("--autonomy", default="interactive",
                   choices=[a.name.lower() for a in Autonomy])
    p.add_argument("--phase", default="recon", choices=[ph.name.lower() for ph in Phase])
    p.add_argument("--model", default=None)
    p.add_argument("--kill-file", default=None,
                   help="touch this path from anywhere to trigger the out-of-band kill switch")
    args = p.parse_args()

    try:
        print(asyncio.run(_run(args)))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
