"""Persist the operator's TUI preferences across sessions.

Two global files:
  config.json    — the chosen provider SELECTION (kind, keys, model). No secrets.
  providers.json — the catalog of bring-your-own custom providers, INCLUDING their
                   api_key so a saved gateway reloads fully usable (like OpenCode/aider).
                   Written 0600 since it holds secrets.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


def config_path() -> Path:
    override = os.environ.get("HEXHARNESS_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hexharness" / "config.json"


def providers_store_path() -> Path:
    override = os.environ.get("HEXHARNESS_PROVIDERS")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "hexharness" / "providers.json"


def load_selection() -> dict | None:
    try:
        return json.loads(config_path().read_text()).get("provider")
    except Exception:  # noqa: BLE001 — missing/corrupt config is just "no saved selection"
        return None


def save_selection(selection: dict) -> None:
    # Defense in depth: config.json is never a secret store, so strip any api_key even
    # if a caller passes a raw custom selection (normally it's a keyless named selection).
    sel = dict(selection)
    if sel.get("kind") == "custom" and "params" in sel:
        sel["params"] = {k: v for k, v in sel["params"].items() if k != "api_key"}
    _write(config_path(), lambda data: data.__setitem__("provider", sel))


def load_custom_providers() -> list[dict]:
    """The saved catalog of bring-your-own providers {name, base_url, model, api_key}."""
    try:
        return json.loads(providers_store_path().read_text()).get("custom_providers") or []
    except Exception:  # noqa: BLE001 — missing/corrupt store is just "no saved customs"
        return []


def save_custom_provider(entry: dict) -> None:
    """Persist one custom provider {name, base_url, model, api_key} to the secret store.
    Deduped by name (last write wins). The api_key IS stored so the provider reloads
    without re-entry; the file is chmod 0600 to keep it operator-only."""
    entry = {k: entry[k] for k in ("name", "base_url", "model", "api_key") if k in entry}

    def mutate(data: dict) -> None:
        saved = [e for e in (data.get("custom_providers") or []) if e.get("name") != entry.get("name")]
        saved.append(entry)
        data["custom_providers"] = saved

    _write(providers_store_path(), mutate, mode=0o600)


def _write(path: Path, mutate, *, mode: int | None = None) -> None:
    """Read-modify-write a JSON file through `mutate`, swallowing IO errors so a config
    write never breaks the UI. `mode` chmods the file best-effort (for the secret store)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            data = {}
        mutate(data)
        path.write_text(json.dumps(data, indent=2))
        if mode is not None:
            try:
                path.chmod(stat.S_IMODE(mode))
            except Exception:  # noqa: BLE001 — perms are best-effort (e.g. Windows)
                pass
    except Exception:  # noqa: BLE001 — never let a config write break the UI
        pass
