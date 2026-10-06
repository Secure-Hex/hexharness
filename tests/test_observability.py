from __future__ import annotations

import pytest

from hexharness.events.bus import EventBus
from hexharness.events.store import EventStore
from hexharness.events.types import EventType
from hexharness.observability.otel import OTelProjector, _NoopTracer


async def _drive(projector: OTelProjector) -> EventStore:
    bus = EventBus()
    projector.attach(bus)
    store = EventStore(":memory:", bus=bus)
    await store.append(EventType.SESSION_STARTED, {"engagement": "t"})
    await store.append(EventType.TOOL_STARTED, {"tool": "port_scan", "input": {"host": "x"}})
    await store.append(EventType.AUTHORIZE_DECISION, {"allowed": True})
    await store.append(EventType.TOOL_FINISHED, {"tool": "port_scan", "ok": True})
    return store


async def test_noop_path_never_raises():
    # No-op tracer stands in for an absent opentelemetry install.
    store = await _drive(OTelProjector(tracer=_NoopTracer()))
    assert store.verify() is True


async def test_spans_recorded_when_otel_present():
    pytest.importorskip("opentelemetry")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    await _drive(OTelProjector(tracer=provider.get_tracer("test")))

    names = [s.name for s in exporter.get_finished_spans()]
    assert EventType.TOOL_STARTED.value in names  # opened+closed tool span
    assert EventType.AUTHORIZE_DECISION.value in names
