"""HexHarness Textual UI. Textual is imported lazily so `import hexharness` never
requires it — only touching HexTUI pulls the dependency in.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hexharness.tui.app import HexTUI

__all__ = ["HexTUI"]


def __getattr__(name: str):  # PEP 562 lazy export
    if name == "HexTUI":
        from hexharness.tui.app import HexTUI

        return HexTUI
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
