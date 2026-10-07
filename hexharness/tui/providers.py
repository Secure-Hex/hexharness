"""Provider catalog for the TUI: detection, lazy construction, in-process registration.

Pure logic, no Textual import — unit-testable on its own. Secrets are written to
`os.environ` for THIS process only; durable storage is a Varlock step, not done here.
"""
from __future__ import annotations

import importlib
import os
import re
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
    # "native" = a dedicated adapter class; "openai_compatible" = the generic adapter
    # pointed at a fixed base_url (OpenRouter, Groq, ...).
    kind: str = "native"
    base_url: str | None = None  # fixed endpoint for openai_compatible entries


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

# OpenAI-compatible gateways: same wire format, different base_url + key. One generic
# adapter serves them all. Base URLs verified against each provider's API docs.
_OAI_COMPAT = [
    ("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai/gpt-4o"),
    ("groq", "Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    ("together", "Together AI", "TOGETHER_API_KEY", "https://api.together.xyz/v1",
     "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    ("deepseek", "DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com", "deepseek-chat"),
    ("xai", "xAI (Grok)", "XAI_API_KEY", "https://api.x.ai/v1", "grok-2-latest"),
    ("mistral", "Mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1", "mistral-large-latest"),
    ("fireworks", "Fireworks", "FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1",
     "accounts/fireworks/models/llama-v3p3-70b-instruct"),
    ("perplexity", "Perplexity", "PERPLEXITY_API_KEY", "https://api.perplexity.ai", "sonar"),
]
CATALOG += [
    ProviderEntry(key, label, (env,), f"HEXHARNESS_{key.upper()}_MODEL", default_model,
                  "hexharness.providers.openai_compatible", "OpenAICompatibleProvider",
                  kind="openai_compatible", base_url=base_url)
    for key, label, env, base_url, default_model in _OAI_COMPAT
]

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _saved_custom(slug: str) -> dict | None:
    """The persisted custom provider (incl. api_key) whose name slugs to `slug`."""
    from hexharness.tui.config import load_custom_providers

    return next((c for c in load_custom_providers() if _slug(c.get("name") or "") == slug), None)


def saved_custom_entries() -> list[ProviderEntry]:
    """One ProviderEntry per persisted custom provider, so saved gateways appear as
    selectable rows. required_env is empty — the key lives in the store, not the env, so
    detect() is always True. build() intercepts custom: keys and uses the stored key."""
    entries: list[ProviderEntry] = []
    from hexharness.tui.config import load_custom_providers

    for c in load_custom_providers():
        name = c.get("name") or "custom"
        entries.append(ProviderEntry(
            key=f"custom:{_slug(name)}", label=f"{name} (custom)",
            required_env=(), model_env="", model_default=c.get("model") or "",
            module="hexharness.providers.openai_compatible", cls_name="OpenAICompatibleProvider",
            kind="openai_compatible", base_url=c.get("base_url"),
        ))
    return entries


def all_entries() -> list[ProviderEntry]:
    return CATALOG + saved_custom_entries()


def entry(key: str) -> ProviderEntry:
    return next(e for e in all_entries() if e.key == key)


def detect(e: ProviderEntry) -> bool:
    """True when every required env var is present. Ollama requires none (local endpoint
    has a default base_url), so it always detects as configured."""
    return all(os.environ.get(k) for k in e.required_env)


def model_for(e: ProviderEntry) -> str:
    return os.environ.get(e.model_env) or e.model_default


def build(e: ProviderEntry, *, model: str | None = None) -> LLMProvider:
    """Construct the provider lazily. The constructor reads its key/base_url from env and
    raises RuntimeError if a required key is missing — so build only on a selected entry."""
    if e.key.startswith("custom:"):
        # Saved bring-your-own gateway: key + base_url live in the secret store, not env.
        c = _saved_custom(e.key.split(":", 1)[1])
        if c is None:
            raise RuntimeError(f"custom provider {e.key!r} not found in the saved store")
        return build_custom(name=c.get("name") or "custom", base_url=c.get("base_url") or "",
                            api_key=c.get("api_key") or "", model=model or c.get("model") or "")
    if e.kind == "openai_compatible":
        from hexharness.providers.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            base_url=e.base_url, default_model=model or model_for(e),
            name=e.key, api_key_env=e.required_env[0],
        )
    cls = getattr(importlib.import_module(e.module), e.cls_name)
    kwargs: dict[str, object] = {}
    if model:
        kwargs["default_model"] = model
    return cls(**kwargs)


def build_custom(*, name: str, base_url: str, api_key: str, model: str) -> LLMProvider:
    """Bring-your-own OpenAI-compatible provider: the operator supplies base_url + key +
    model at runtime (e.g. a self-hosted gateway). The key is passed directly, never env."""
    from hexharness.providers.openai_compatible import OpenAICompatibleProvider

    return OpenAICompatibleProvider(
        base_url=base_url, default_model=model or "", name=name or "custom", api_key=api_key,
    )


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
