"""Cost-aware routing over several LLMProvider backends.

Picks the cheapest route that advertises a required capability (default "chat") and
falls back to the next-cheapest route when a provider call raises. Selection is
deterministic: routes are ordered by (in+out $/Mtok, declaration order).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from hexharness.providers.types import Message, ModelResponse, ToolSpec, Usage


@dataclass(frozen=True)
class Route:
    provider: object  # LLMProvider — kept loose so fakes/adapters both fit.
    models: list[str]
    cost_per_mtok_in: float
    cost_per_mtok_out: float
    capabilities: set[str] = field(default_factory=lambda: {"chat"})

    @property
    def unit_cost(self) -> float:
        return self.cost_per_mtok_in + self.cost_per_mtok_out


def estimate_usd(usage: Usage, route: Route) -> float:
    return (
        usage.input_tokens / 1_000_000 * route.cost_per_mtok_in
        + usage.output_tokens / 1_000_000 * route.cost_per_mtok_out
    )


class Router:
    name = "router"

    def __init__(self, routes: list[Route]):
        if not routes:
            raise ValueError("Router needs at least one route")
        self._routes = list(routes)

    def _candidates(self, capability: str) -> list[Route]:
        matching = [r for r in self._routes if capability in r.capabilities]
        # Stable sort keeps declaration order as the deterministic tie-breaker.
        return sorted(matching, key=lambda r: r.unit_cost)

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        on_text=None,
        on_thinking=None,
        capability: str = "chat",
    ) -> ModelResponse:
        candidates = self._candidates(capability)
        if not candidates:
            raise ValueError(f"no route advertises capability {capability!r}")
        last_exc: Exception | None = None
        for route in candidates:
            try:
                return await route.provider.complete(
                    messages,
                    tools=tools,
                    system=system,
                    model=model or route.models[0],
                    max_tokens=max_tokens,
                    on_text=on_text,
                    on_thinking=on_thinking,
                )
            except Exception as exc:  # fall back to the next-cheapest route
                last_exc = exc
        raise RuntimeError("all routes failed") from last_exc
