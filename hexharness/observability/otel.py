"""OTel projection of the event stream.

The Audit Log, tracing and checkpointing are three PROJECTIONS of the one
append-only event stream. This is the tracing projection: it SUBSCRIBES to the
EventBus and maps each event to an OpenTelemetry span. It never produces events.

opentelemetry is imported lazily; if the SDK isn't installed the projector falls
back to a no-op tracer so the engine still runs. Install with the [otel] extra.
"""
from __future__ import annotations

from typing import Any

from hexharness.events.types import Event, EventType


class _NoopSpan:
    # ponytail: minimal no-op so the engine runs without opentelemetry installed.
    def set_attribute(self, *_a: Any, **_k: Any) -> None: ...
    def add_event(self, *_a: Any, **_k: Any) -> None: ...
    def end(self, *_a: Any, **_k: Any) -> None: ...


class _NoopTracer:
    def start_span(self, *_a: Any, **_k: Any) -> _NoopSpan:
        return _NoopSpan()


def _default_tracer() -> Any:
    try:
        from opentelemetry import trace  # lazy: optional [otel] dependency
    except ImportError:
        return _NoopTracer()
    return trace.get_tracer("hexharness")


def _scalar(v: Any) -> str | int | float | bool:
    # OTel attributes accept only scalars/sequences; stringify anything else.
    return v if isinstance(v, (str, int, float, bool)) else str(v)


class OTelProjector:
    """Subscribe to an EventBus and emit one span per event.

    TOOL_STARTED opens a span kept open until the matching TOOL_FINISHED closes it;
    every other event (AUTHORIZE_DECISION included) becomes a short span carrying the
    payload as attributes.
    """

    def __init__(self, tracer: Any | None = None) -> None:
        self._tracer = tracer or _default_tracer()
        # ponytail: keyed by tool name; last-opened wins on same-name overlap.
        # Add a span-id in the TOOL_* payloads if concurrent same-tool spans ever matter.
        self._open: dict[str, Any] = {}

    def attach(self, bus: Any) -> None:
        bus.subscribe(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.type is EventType.TOOL_STARTED:
            span = self._tracer.start_span(event.type.value)
            for k, v in event.payload.items():
                span.set_attribute(k, _scalar(v))
            self._open[str(event.payload.get("tool"))] = span
            return

        if event.type is EventType.TOOL_FINISHED:
            span = self._open.pop(str(event.payload.get("tool")), None)
            if span is not None:
                for k, v in event.payload.items():
                    span.set_attribute(k, _scalar(v))
                span.end()
            return

        span = self._tracer.start_span(event.type.value)
        span.set_attribute("seq", event.seq)
        for k, v in event.payload.items():
            span.set_attribute(k, _scalar(v))
        span.end()
