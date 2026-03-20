"""Tests for OpenTelemetry distributed tracing setup."""

from unittest.mock import MagicMock, patch

import pytest


class TestInitFastapiTracing:
    """Tests for init_fastapi_tracing."""

    def test_noop_when_endpoint_empty(self) -> None:
        """When OSINT_OTEL_ENDPOINT is empty, no instrumentation occurs."""
        with patch("osint_core.tracing.settings") as mock_settings:
            mock_settings.otel_endpoint = ""
            from osint_core.tracing import init_fastapi_tracing

            mock_app = MagicMock()
            with patch("osint_core.tracing._init_tracer") as mock_init:
                init_fastapi_tracing(mock_app)
                mock_init.assert_not_called()

    def test_instruments_when_endpoint_set(self) -> None:
        """When OSINT_OTEL_ENDPOINT is set, FastAPI is instrumented."""
        import opentelemetry.instrumentation.fastapi as fastapi_mod

        with (
            patch("osint_core.tracing.settings") as mock_settings,
            patch("osint_core.tracing._init_tracer") as mock_init,
            patch.object(
                fastapi_mod.FastAPIInstrumentor, "instrument_app"
            ) as mock_instrument,
        ):
            mock_settings.otel_endpoint = "http://jaeger:4317"
            mock_settings.otel_sample_rate = 0.1
            from osint_core.tracing import init_fastapi_tracing

            mock_app = MagicMock()
            init_fastapi_tracing(mock_app)

            mock_init.assert_called_once()
            mock_instrument.assert_called_once_with(mock_app)


class TestInitCeleryTracing:
    """Tests for init_celery_tracing."""

    def test_noop_when_endpoint_empty(self) -> None:
        """When OSINT_OTEL_ENDPOINT is empty, no instrumentation occurs."""
        with patch("osint_core.tracing.settings") as mock_settings:
            mock_settings.otel_endpoint = ""
            from osint_core.tracing import init_celery_tracing

            with patch("osint_core.tracing._init_tracer") as mock_init:
                init_celery_tracing()
                mock_init.assert_not_called()

    def test_instruments_when_endpoint_set(self) -> None:
        """When OSINT_OTEL_ENDPOINT is set, Celery is instrumented."""
        import opentelemetry.instrumentation.celery as celery_mod

        mock_instrumentor = MagicMock()
        with (
            patch("osint_core.tracing.settings") as mock_settings,
            patch("osint_core.tracing._init_tracer") as mock_init,
            patch.object(
                celery_mod, "CeleryInstrumentor", return_value=mock_instrumentor
            ),
        ):
            mock_settings.otel_endpoint = "http://jaeger:4317"
            mock_settings.otel_sample_rate = 0.1
            from osint_core.tracing import init_celery_tracing

            init_celery_tracing()

            mock_init.assert_called_once()
            mock_instrumentor.instrument.assert_called_once()


class TestInitTracer:
    """Tests for _init_tracer internal function."""

    def test_creates_tracer_provider(self) -> None:
        """_init_tracer configures a TracerProvider with OTLP exporter and sampler."""
        with (
            patch("osint_core.tracing.settings") as mock_settings,
            patch("opentelemetry.sdk.trace.TracerProvider") as mock_provider_cls,
            patch("opentelemetry.sdk.trace.export.BatchSpanProcessor") as mock_processor_cls,
            patch(
                "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"
            ) as mock_exporter_cls,
            patch("opentelemetry.sdk.trace.sampling.TraceIdRatioBased") as mock_sampler_cls,
            patch("opentelemetry.sdk.resources.Resource.create") as mock_resource_create,
            patch("opentelemetry.trace.set_tracer_provider") as mock_set_provider,
        ):
            mock_settings.otel_endpoint = "http://jaeger:4317"
            mock_settings.otel_sample_rate = 0.5

            mock_resource = MagicMock()
            mock_resource_create.return_value = mock_resource
            mock_sampler = MagicMock()
            mock_sampler_cls.return_value = mock_sampler
            mock_provider = MagicMock()
            mock_provider_cls.return_value = mock_provider
            mock_exporter = MagicMock()
            mock_exporter_cls.return_value = mock_exporter
            mock_processor = MagicMock()
            mock_processor_cls.return_value = mock_processor

            from osint_core.tracing import _init_tracer

            _init_tracer()

            mock_resource_create.assert_called_once_with({"service.name": "osint-core"})
            mock_sampler_cls.assert_called_once_with(0.5)
            mock_provider_cls.assert_called_once_with(resource=mock_resource, sampler=mock_sampler)
            mock_exporter_cls.assert_called_once_with(endpoint="http://jaeger:4317")
            mock_processor_cls.assert_called_once_with(mock_exporter)
            mock_provider.add_span_processor.assert_called_once_with(mock_processor)
            mock_set_provider.assert_called_once_with(mock_provider)


class TestCeleryWorkerProcessInit:
    """Tests for the worker_process_init signal handler."""

    def test_worker_process_init_calls_init_celery_tracing(self) -> None:
        """The worker_process_init signal handler calls init_celery_tracing."""
        with patch("osint_core.tracing.init_celery_tracing") as mock_init:
            from osint_core.workers.celery_app import on_worker_process_init

            on_worker_process_init(sender=None)
            mock_init.assert_called_once()


class TestTracingConfig:
    """Tests for tracing-related config settings."""

    def test_otel_endpoint_defaults_to_empty(self) -> None:
        """OSINT_OTEL_ENDPOINT defaults to empty string (tracing disabled)."""
        from osint_core.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
            celery_broker_url="redis://localhost:6379/1",
            celery_result_backend="redis://localhost:6379/2",
        )
        assert s.otel_endpoint == ""

    def test_otel_sample_rate_defaults_to_point_one(self) -> None:
        """OSINT_OTEL_SAMPLE_RATE defaults to 0.1."""
        from osint_core.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/0",
            celery_broker_url="redis://localhost:6379/1",
            celery_result_backend="redis://localhost:6379/2",
        )
        assert s.otel_sample_rate == pytest.approx(0.1)

    def test_otel_endpoint_configurable_via_env(self) -> None:
        """OSINT_OTEL_ENDPOINT can be set via environment variable."""
        with patch.dict("os.environ", {"OSINT_OTEL_ENDPOINT": "http://jaeger:4317"}):
            from osint_core.config import Settings

            s = Settings(
                database_url="postgresql+asyncpg://test:test@localhost:5432/test",
                redis_url="redis://localhost:6379/0",
                celery_broker_url="redis://localhost:6379/1",
                celery_result_backend="redis://localhost:6379/2",
            )
            assert s.otel_endpoint == "http://jaeger:4317"

    def test_otel_sample_rate_configurable_via_env(self) -> None:
        """OSINT_OTEL_SAMPLE_RATE can be set via environment variable."""
        with patch.dict("os.environ", {"OSINT_OTEL_SAMPLE_RATE": "0.5"}):
            from osint_core.config import Settings

            s = Settings(
                database_url="postgresql+asyncpg://test:test@localhost:5432/test",
                redis_url="redis://localhost:6379/0",
                celery_broker_url="redis://localhost:6379/1",
                celery_result_backend="redis://localhost:6379/2",
            )
            assert s.otel_sample_rate == pytest.approx(0.5)
