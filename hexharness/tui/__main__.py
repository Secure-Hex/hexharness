"""Entry point: `python -m hexharness.tui [--engagement PATH]`."""
from __future__ import annotations

import argparse

from hexharness.tui.app import DEFAULT_ENGAGEMENT, HexTUI


def main() -> int:
    p = argparse.ArgumentParser(prog="hexharness.tui", description="HexHarness terminal UI")
    p.add_argument("--engagement", default=DEFAULT_ENGAGEMENT,
                   help="path to the engagement YAML to run under")
    args = p.parse_args()
    HexTUI(engagement=args.engagement).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
