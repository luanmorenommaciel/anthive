"""anthive observability — OTEL tracing init, session span, lifecycle events.

Public API:
    init_tracing(service_name, endpoint, *, resource_attributes) -> None
    session_span(session_id, task_id, agent, mode) -> ContextManager
    emit_lifecycle_event(session_id, from_state, to_state, note) -> None

Design rules:
- init_tracing is idempotent: second call is a no-op.
- A missing/unreachable OTLP endpoint never crashes the CLI.
- session_span always yields a valid span (no-op if not initialized).
- emit_lifecycle_event is safe to call with no active span.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NonRecordingSpan, Span

__all__ = ["init_tracing", "session_span", "emit_lifecycle_event"]

logger = logging.getLogger(__name__)

_initialized: bool = False


def init_tracing(
    service_name: str = "anthive",
    endpoint: str | None = None,
    *,
    resource_attributes: dict[str, str] | None = None,
) -> None:
    """Initialize OTEL → OTLP HTTP exporter. Idempotent; safe to call once."""
    global _initialized  # noqa: PLW0603

    if _initialized:
        logger.debug("init_tracing: already initialized, skipping.")
        return

    resolved_endpoint = endpoint or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:3000/api/public/otel"
    )

    attrs: dict[str, str] = {"service.name": service_name}
    if resource_attributes:
        attrs.update(resource_attributes)

    resource = Resource.create(attrs)

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=resolved_endpoint)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized = True
        logger.debug("init_tracing: OTLP exporter configured at %s", resolved_endpoint)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "init_tracing: could not configure OTLP exporter at %s (%s). "
            "Falling back to no-op tracer.",
            resolved_endpoint,
            exc,
        )
        # Do NOT set _initialized — let the no-op tracer handle it gracefully.


@contextmanager
def session_span(
    session_id: str,
    task_id: str,
    agent: str,
    mode: str,
) -> Generator[Span, None, None]:
    """Context manager that opens a parent 'anthive.session' span.

    Works even when tracing was never initialized (falls back to no-op span).
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "anthive.session",
        attributes={
            "anthive.session_id": session_id,
            "anthive.task_id": task_id,
            "anthive.agent": agent,
            "anthive.mode": mode,
        },
    ) as span:
        yield span


def emit_lifecycle_event(
    session_id: str,
    from_state: str,
    to_state: str,
    note: str = "",
) -> None:
    """Record a lifecycle transition as an event on the current span."""
    span = trace.get_current_span()

    if isinstance(span, NonRecordingSpan):
        logger.debug(
            "emit_lifecycle_event: no active recording span; event dropped "
            "(session_id=%s, %s→%s).",
            session_id,
            from_state,
            to_state,
        )
        return

    span.add_event(
        "lifecycle_transition",
        attributes={
            "anthive.session_id": session_id,
            "from": from_state,
            "to": to_state,
            "note": note,
        },
    )
