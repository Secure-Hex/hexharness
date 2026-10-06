"""Token -> USD pricing so the Budget's usd cap actually fires.

Prices are USD per million tokens, matched by model-id prefix. Unknown models price
at 0 (the usd cap simply can't bind for them) — the token and time caps still apply.
Update the table as models change; it is config data, not logic.
"""
from __future__ import annotations

from hexharness.providers.types import Usage

# model-id prefix -> (usd_per_million_input, usd_per_million_output)
_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.80, 4.0),
    "gpt-4o": (2.5, 10.0),
    "gemini-2.0-flash": (0.10, 0.40),
}


def price_for(model: str) -> tuple[float, float]:
    for prefix, price in _PRICES.items():
        if model.startswith(prefix):
            return price
    return (0.0, 0.0)  # ponytail: unknown model => usd cap inactive; token/time caps still bind


def usd_cost(model: str, usage: Usage) -> float:
    pin, pout = price_for(model)
    return usage.input_tokens / 1_000_000 * pin + usage.output_tokens / 1_000_000 * pout
