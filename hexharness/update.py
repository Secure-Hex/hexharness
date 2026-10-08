"""Check PyPI for a newer HexHarness and let the operator decide. Best-effort and
fail-safe: no network, a slow mirror, or a dev checkout never blocks or raises — the
check just returns None and the app runs the installed version.

Set HEXHARNESS_NO_UPDATE_CHECK=1 to disable the check entirely.
"""
from __future__ import annotations

import json
import os
import urllib.request
from importlib.metadata import PackageNotFoundError, version

_PYPI_JSON = "https://pypi.org/pypi/hexharness/json"


def current_version() -> str | None:
    try:
        return version("hexharness")
    except PackageNotFoundError:
        return None


def latest_version(*, timeout: float = 2.0) -> str | None:
    """The newest version on PyPI, or None if it can't be fetched quickly."""
    try:
        with urllib.request.urlopen(_PYPI_JSON, timeout=timeout) as resp:
            return json.load(resp)["info"]["version"]
    except Exception:  # noqa: BLE001 — offline/timeout/parse: never fatal
        return None


def _parse(v: str) -> tuple:
    # Compare release numbers numerically (1.10.0 > 1.9.0); ignore pre/build suffixes.
    nums = []
    for part in v.split(".")[:3]:
        n = "".join(c for c in part if c.isdigit())
        nums.append(int(n) if n else 0)
    return tuple(nums)


def check_update(*, timeout: float = 2.0) -> tuple[str, str] | None:
    """Return (current, latest) when a newer release is available, else None.
    Honors HEXHARNESS_NO_UPDATE_CHECK and never raises."""
    if os.environ.get("HEXHARNESS_NO_UPDATE_CHECK"):
        return None
    cur = current_version()
    if not cur:
        return None
    latest = latest_version(timeout=timeout)
    if not latest:
        return None
    if _parse(latest) > _parse(cur):
        return (cur, latest)
    return None


def upgrade() -> tuple[bool, str]:
    """Run `pip install -U hexharness`. Returns (ok, output tail). The caller restarts."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-U", "hexharness"],
        capture_output=True, text=True,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out[-800:]
