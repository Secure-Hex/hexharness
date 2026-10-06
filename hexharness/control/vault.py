"""Secrets vault. Resolves named secrets without letting their values reach logs,
events or the LLM context. Backed by env today; the upgrade path is Varlock-managed
`.env` so secrets never sit in plain env either.

# ponytail: env-backed resolver with redaction now; swap _resolve for a Varlock client
# when secret sprawl justifies it — the redaction API stays the same.
"""
from __future__ import annotations

import os


class SecretNotFound(KeyError):
    pass


class Vault:
    def __init__(self, *, env_prefix: str = ""):
        self._env_prefix = env_prefix
        self._known: set[str] = set()
        self._store: dict[str, str] = {}  # in-process secrets set at runtime (never on disk)

    def set(self, name: str, value: str) -> None:
        """Store a secret handed over out-of-band (e.g. an operator pastes an API key).
        Lives in-process only. ponytail: add an OS-keyring backend to persist across runs."""
        self._store[name] = value
        self._known.add(value)

    def get(self, name: str) -> str:
        if name in self._store:
            value = self._store[name]
        else:
            value = os.environ.get(f"{self._env_prefix}{name}")
        if value is None:
            raise SecretNotFound(name)
        self._known.add(value)
        return value

    def has(self, name: str) -> bool:
        return name in self._store or f"{self._env_prefix}{name}" in os.environ

    def names(self) -> list[str]:
        """Names of secrets currently held — NEVER the values (safe to show in a UI)."""
        import os as _os

        env_names = [k for k in _os.environ if k.endswith("_API_KEY") or k.startswith(self._env_prefix)]
        return sorted(set(self._store) | set(env_names))

    def redact(self, text: str) -> str:
        """Scrub any resolved secret value out of a string before it is logged or
        emitted as an event. Only redacts values actually handed out by this vault."""
        out = text
        for secret in self._known:
            if secret:
                out = out.replace(secret, "***REDACTED***")
        return out
