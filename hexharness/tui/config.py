"""Persist the operator's non-secret TUI preferences across sessions.

Stores the chosen provider SELECTION (kind, keys, model) so a new session reuses it.
NEVER stores API keys — those live in the env/vault, not on disk (opsec). A custom
provider's base_url/name/model persist; its key must be re-entered next session.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("HEXHARNESS_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hexharness" / "config.json"


def _sanitize(sel: dict) -> dict:
    sel = deepcopy(sel)
    if sel.get("kind") == "custom":
        sel.get("params", {}).pop("api_key", None)  # never persist secrets
    return sel


def load_selection() -> dict | None:
    try:
        return json.loads(config_path().read_text()).get("provider")
    except Exception:  # noqa: BLE001 — missing/corrupt config is just "no saved selection"
        return None


def save_selection(selection: dict) -> None:
    try:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            data = {}
        data["provider"] = _sanitize(selection)
        path.write_text(json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001 — never let a config write break the UI
        pass
