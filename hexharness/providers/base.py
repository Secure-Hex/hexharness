from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from hexharness.providers.types import Message, ModelResponse, ToolSpec

# Called with each text delta as it arrives. None = no streaming (one blocking call).
TextSink = Callable[[str], None]


@runtime_checkable
class LLMProvider(Protocol):
    """Capability-normalized LLM port. Adapters (Anthropic, OpenAI, ...) implement it."""

    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        on_text: TextSink | None = None,
    ) -> ModelResponse: ...
