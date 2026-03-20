"""OpenTelemetry distributed tracing setup.

Initialises a TracerProvider with an OTLP exporter when ``OSINT_OTEL_ENDPOINT``
is set.  When the endpoint is empty (the default), tracing is disabled and this
module is a no-op.
"""

from __future__ import annotations

import structlog

from osint_core.config import settings

logger = structlog.get_logger()


def _init_tracer() -> None:
    """Configure the global OpenTelemetry TracerProvider.

    Called once during application startup.  Safe to call multiple times — the
    first invocation wins because ``set_tracer_provider`` is idempotent when
    the provider is already set.
    """
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    resource = Resource.create({"service.name": "osint-core"})
    sampler = TraceIdRatioBased(settings.otel_sample_rate)
    provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(
        "otel_tracing_enabled",
        endpoint=settings.otel_endpoint,
        sample_rate=settings.otel_sample_rate,
    )


def init_fastapi_tracing(app: object) -> None:
    """Instrument a FastAPI application with OpenTelemetry.

    No-op when ``OSINT_OTEL_ENDPOINT`` is empty.
    """
    if not settings.otel_endpoint:
        return

    _init_tracer()

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]
    logger.info("otel_fastapi_instrumented")


def init_celery_tracing() -> None:
    """Instrument Celery with OpenTelemetry.

    Designed to be called from the ``worker_process_init`` signal so each
    worker process gets its own TracerProvider.  No-op when
    ``OSINT_OTEL_ENDPOINT`` is empty.
    """
    if not settings.otel_endpoint:
        return

    _init_tracer()

    from opentelemetry.instrumentation.celery import CeleryInstrumentor

    CeleryInstrumentor().instrument()
    logger.info("otel_celery_instrumented")
