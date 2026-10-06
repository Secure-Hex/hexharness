"""Provider catalog for the TUI: detection, lazy construction, in-process registration.

Pure logic, no Textual import — unit-testable on its own. Secrets are written to
`os.environ` for THIS process only; durable storage is a Varlock step, not done here.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

from hexharness.providers.base import LLMProvider


@dataclass(frozen=True)
class ProviderEntry:
    key: str                     # stable id: anthropic | openai | google | ollama
    label: str
    required_env: tuple[str, ...]  # all must be present for the entry to be "configured"
    model_env: str               # env var that overrides the default model
    model_default: str
    module: str                  # hexharness.providers.<module>
    cls_name: str
    needs_base_url: bool = False
    base_url_env: str | None = None
    # $/Mtok (in, out) — a small default table; only used to build a Router.
    cost: tuple[float, float] = (1.0, 1.0)


# ponytail: one flat list is the whole registry; no plugin loader until a 5th provider
# needs to come from outside this package.
CATALOG: list[ProviderEntry] = [
    ProviderEntry("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",),
                  "HEXHARNESS_MODEL", "claude-sonnet-4-5",
                  "hexharness.providers.anthropic", "AnthropicProvider", cost=(3.0, 15.0)),
    ProviderEntry("openai", "OpenAI", ("OPENAI_API_KEY",),
                  "HEXHARNESS_OPENAI_MODEL", "gpt-4o",
                  "hexharness.providers.openai", "OpenAIProvider", cost=(2.5, 10.0)),
    ProviderEntry("google", "Google", ("GOOGLE_API_KEY",),
                  "HEXHARNESS_GOOGLE_MODEL", "gemini-2.0-flash",
                  "hexharness.providers.google", "GoogleProvider", cost=(0.1, 0.4)),
    ProviderEntry("ollama", "Ollama (local)", (),
                  "HEXHARNESS_OLLAMA_MODEL", "llama3.1",
                  "hexharness.providers.ollama", "OllamaProvider",
                  needs_base_url=True, base_url_env="OLLAMA_BASE_URL", cost=(0.0, 0.0)),
]

_BY_KEY = {e.key: e for e in CATALOG}


def entry(key: str) -> ProviderEntry:
    return _BY_KEY[key]


def detect(e: ProviderEntry) -> bool:
    """True when every required env var is present. Ollama requires none (local endpoint
    has a default base_url), so it always detects as configured."""
    return all(os.environ.get(k) for k in e.required_env)


def model_for(e: ProviderEntry) -> str:
    return os.environ.get(e.model_env) or e.model_default


def build(e: ProviderEntry, *, model: str | None = None) -> LLMProvider:
    """Construct the provider lazily. The constructor reads its key/base_url from env and
    raises RuntimeError if a required key is missing — so build only on a selected entry."""
    cls = getattr(importlib.import_module(e.module), e.cls_name)
    kwargs: dict[str, object] = {}
    if model:
        kwargs["default_model"] = model
    return cls(**kwargs)


def register(e: ProviderEntry, values: dict[str, str]) -> None:
    """Set the entry's secrets/config into os.environ for this process only.
    `values` is keyed by env var name (e.g. {"ANTHROPIC_API_KEY": "...", <model_env>: "..."}).
    Empty values are ignored so a blank field never clobbers an existing var.

    # ponytail: in-memory only — persisting these is a Varlock step, deliberately not here.
    """
    for k, v in values.items():
        if v:
            os.environ[k] = v


def router_spec(entries: list[ProviderEntry], *, models: dict[str, str] | None = None):
    """Build a Router over the selected entries. Selection order is the declared fallback
    order; note the Router re-sorts routes by unit cost (declaration order breaks ties),
    so the cheapest configured route is tried first."""
    from hexharness.providers.router import Route, Router

    models = models or {}
    routes = [
        Route(
            provider=build(e, model=models.get(e.key) or model_for(e)),
            models=[models.get(e.key) or model_for(e)],
            cost_per_mtok_in=e.cost[0],
            cost_per_mtok_out=e.cost[1],
        )
        for e in entries
    ]
    return Router(routes)
