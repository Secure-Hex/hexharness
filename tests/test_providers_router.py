"""Router selection and fallback — no SDKs, no network, tiny fake providers."""
from __future__ import annotations

import pytest

from hexharness.providers.router import Route, Router, estimate_usd
from hexharness.providers.types import Message, ModelResponse, StopReason, TextBlock, Usage


class _Fake:
    def __init__(self, name: str, *, boom: bool = False):
        self.name = name
        self.boom = boom
        self.calls = 0

    async def complete(self, messages, *, tools=None, system=None, model=None, max_tokens=4096):
        self.calls += 1
        if self.boom:
            raise RuntimeError(f"{self.name} down")
        return ModelResponse(
            content=[TextBlock(text=self.name)], stop_reason=StopReason.END_TURN, model=model or ""
        )


def _route(provider, cost_in, cost_out, caps={"chat"}, models=("m",)):
    return Route(provider, list(models), cost_in, cost_out, set(caps))


async def test_picks_cheapest_matching_route():
    cheap, pricey = _Fake("cheap"), _Fake("pricey")
    r = Router([_route(pricey, 10, 30), _route(cheap, 1, 2)])
    resp = await r.complete([Message.user_text("hi")])
    assert resp.text() == "cheap"
    assert cheap.calls == 1 and pricey.calls == 0


async def test_falls_back_on_provider_exception():
    broken, backup = _Fake("broken", boom=True), _Fake("backup")
    r = Router([_route(broken, 1, 1), _route(backup, 5, 5)])
    resp = await r.complete([Message.user_text("hi")])
    assert resp.text() == "backup"
    assert broken.calls == 1 and backup.calls == 1


async def test_capability_filter_excludes_non_matching():
    chat_only, vision = _Fake("chat"), _Fake("vision")
    r = Router([_route(chat_only, 100, 100, caps={"chat"}), _route(vision, 1, 1, caps={"vision"})])
    resp = await r.complete([Message.user_text("hi")], capability="vision")
    assert resp.text() == "vision"


async def test_raises_when_no_capability_match():
    r = Router([_route(_Fake("x"), 1, 1, caps={"chat"})])
    with pytest.raises(ValueError):
        await r.complete([Message.user_text("hi")], capability="embeddings")


async def test_all_routes_failing_raises():
    r = Router([_route(_Fake("a", boom=True), 1, 1), _route(_Fake("b", boom=True), 2, 2)])
    with pytest.raises(RuntimeError):
        await r.complete([Message.user_text("hi")])


async def test_default_model_from_route_when_unspecified():
    fake = _Fake("f")
    r = Router([Route(fake, ["best-model"], 1, 1, {"chat"})])
    resp = await r.complete([Message.user_text("hi")])
    assert resp.model == "best-model"


def test_estimate_usd():
    route = _route(_Fake("f"), cost_in=3.0, cost_out=15.0)
    usd = estimate_usd(Usage(input_tokens=1_000_000, output_tokens=500_000), route)
    assert usd == pytest.approx(3.0 + 7.5)


def test_empty_router_rejected():
    with pytest.raises(ValueError):
        Router([])
