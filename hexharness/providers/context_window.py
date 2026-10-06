"""Context-window sizes per model, matched by model-id prefix (like pricing.py).

The window caps how much conversation fits. We learn actual usage from each response's
usage.input_tokens (the size of the context that was just sent), and compare it to the
window to decide when to compact. Unknown models fall back to a conservative default so
compaction triggers early rather than overflowing.
"""
from __future__ import annotations

# Ordered most-specific first; first prefix match wins. Sizes in tokens.
_WINDOWS: list[tuple[str, int]] = [
    ("claude-", 200_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("o1", 200_000),
    ("gpt-", 128_000),
    ("gemini-1.5", 1_000_000),
    ("gemini-2", 1_000_000),
    ("gemini", 1_000_000),
    ("grok", 131_072),
    ("deepseek", 128_000),
    ("mistral", 128_000),
    ("llama", 128_000),
    ("qwen", 32_768),
]
DEFAULT_WINDOW = 128_000


def window_for(model: str) -> int:
    model = model or ""
    for prefix, size in _WINDOWS:
        if model.startswith(prefix):
            return size
    return DEFAULT_WINDOW


def usage_ratio(model: str, input_tokens: int) -> float:
    return input_tokens / window_for(model)


def should_compact(model: str, input_tokens: int, threshold: float = 0.8) -> bool:
    return input_tokens >= threshold * window_for(model)
