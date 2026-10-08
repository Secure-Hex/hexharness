"""Secrets vault. Resolves named secrets without letting their values reach logs,
events or the LLM context. Backed by env today; the upgrade path is Varlock-managed
`.env` so secrets never sit in plain env either.

# ponytail: env-backed resolver with redaction now; swap _resolve for a Varlock client
# when secret sprawl justifies it — the redaction API stays the same.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class SecretNotFound(KeyError):
    pass


def _get_fernet():
    """Return cryptography's Fernet class, or None if it isn't installed.
    Isolated so tests can monkeypatch it to simulate a crypto-less install."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    return Fernet


class Vault:
    def __init__(self, *, env_prefix: str = "", persist_path: str | os.PathLike | None = None):
        self._env_prefix = env_prefix
        self._known: set[str] = set()
        self._store: dict[str, str] = {}  # in-process secrets set at runtime
        # Optional encrypted-at-rest persistence. Key lives beside the store file.
        self._persist_path = Path(persist_path).expanduser() if persist_path else None
        self._key_path = self._persist_path.with_name("vault.key") if self._persist_path else None
        if self._persist_path:
            self._load()

    # --- encrypted persistence (no-op unless a path is set AND cryptography is present) ---

    def persistence_available(self) -> bool:
        """True when secrets set() will actually survive the process. A UI can show this."""
        return self._persist_path is not None and _get_fernet() is not None

    def _fernet(self):
        """Load (or generate) the 0600 key and return a Fernet, or None if crypto is absent."""
        Fernet = _get_fernet()
        if Fernet is None or self._key_path is None:
            return None  # ponytail: no crypto -> caller must NOT write plaintext
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._key_path.parent, 0o700)  # dir needs exec to traverse; 0700 not 0600
        if self._key_path.exists():
            key = self._key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self._write_0600(self._key_path, key)
        return Fernet(key)

    def _load(self) -> None:
        f = self._fernet()
        if f is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(f.decrypt(self._persist_path.read_bytes()))
        except Exception:
            return  # ponytail: corrupt/old-key file -> start empty, keep running
        self._store.update(data)
        self._known.update(data.values())  # loaded values are redactable like set() ones

    def _save(self) -> None:
        f = self._fernet()
        if f is None:
            return  # fail safe: never write secret values unencrypted
        token = f.encrypt(json.dumps(self._store).encode())
        self._write_0600(self._persist_path, token)

    @staticmethod
    def _write_0600(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(path, 0o600)  # tighten even if the file pre-existed with looser perms

    # --- API (unchanged surface) ---

    def set(self, name: str, value: str) -> None:
        """Store a secret handed over out-of-band (e.g. an operator pastes an API key).
        Persisted encrypted-at-rest if a persist_path was given and cryptography is installed,
        otherwise in-process only."""
        self._store[name] = value
        self._known.add(value)
        if self._persist_path:
            self._save()

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
        # Only surface likely-secret env vars: those ending in _API_KEY, or (when a prefix
        # is configured) matching it. An empty prefix must NOT match the whole environment.
        env_names = [k for k in os.environ if k.endswith("_API_KEY")
                     or (self._env_prefix and k.startswith(self._env_prefix))]
        return sorted(set(self._store) | set(env_names))

    def redact(self, text: str) -> str:
        """Scrub any resolved secret value out of a string before it is logged or
        emitted as an event. Only redacts values actually handed out by this vault."""
        out = text
        for secret in self._known:
            if secret:
                out = out.replace(secret, "***REDACTED***")
        return out
