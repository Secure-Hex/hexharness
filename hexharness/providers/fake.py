"""Scripted provider for offline demo and tests.

NOT a mock of real infrastructure — the "no mocks" invariant applies to tools and
the sandbox (which must be real), not to the LLM in unit tests. This just replays a
pre-baked list of ModelResponse objects so the loop and control plane can be exercised
deterministically without a network call.
"""
from __future__ import annotations

from hexharness.providers.types import Message, ModelResponse, ToolSpec


class FakeProvider:
    name = "fake"

    def __init__(self, scripted: list[ModelResponse]):
        self._scripted = list(scripted)
        self.calls: list[list[Message]] = []

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
    ) -> ModelResponse:
        self.calls.append(list(messages))
        if not self._scripted:
            raise AssertionError("FakeProvider ran out of scripted responses")
        resp = self._scripted.pop(0)
        if on_text is not None:
            text = resp.text()
            if text:
                on_text(text)  # single synthetic delta — deterministic for tests
        return resp
