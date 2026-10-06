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

    def get(self, name: str) -> str:
        key = f"{self._env_prefix}{name}"
        value = os.environ.get(key)
        if value is None:
            raise SecretNotFound(key)
        self._known.add(value)
        return value

    def has(self, name: str) -> bool:
        return f"{self._env_prefix}{name}" in os.environ

    def redact(self, text: str) -> str:
        """Scrub any resolved secret value out of a string before it is logged or
        emitted as an event. Only redacts values actually handed out by this vault."""
        out = text
        for secret in self._known:
            if secret:
                out = out.replace(secret, "***REDACTED***")
        return out
