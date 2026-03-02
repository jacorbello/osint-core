"""Tests for custom Prometheus metrics."""

from fastapi.testclient import TestClient

from osint_core.main import app
from osint_core import metrics


def test_metrics_endpoint():
    """GET /metrics returns 200 with prometheus content-type."""
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"] or "text/plain" in resp.text[:0] or resp.headers["content-type"].startswith("text/")


def test_custom_metrics_registered():
    """Verify custom counters/histograms/gauges exist as module-level objects."""
    assert hasattr(metrics, "events_ingested")
    assert hasattr(metrics, "alerts_fired")
    assert hasattr(metrics, "ingestion_duration")
    assert hasattr(metrics, "active_jobs")
    assert hasattr(metrics, "celery_queue_depth")


def test_events_ingested_counter_increments():
    """The events_ingested counter can be labelled and incremented."""
    before = metrics.events_ingested.labels(source_id="test-src")._value.get()
    metrics.events_ingested.labels(source_id="test-src").inc()
    after = metrics.events_ingested.labels(source_id="test-src")._value.get()
    assert after == before + 1


def test_alerts_fired_counter_increments():
    """The alerts_fired counter can be labelled and incremented."""
    before = metrics.alerts_fired.labels(severity="high", route="default")._value.get()
    metrics.alerts_fired.labels(severity="high", route="default").inc()
    after = metrics.alerts_fired.labels(severity="high", route="default")._value.get()
    assert after == before + 1


def test_ingestion_duration_histogram_observe():
    """The ingestion_duration histogram accepts observations."""
    metrics.ingestion_duration.labels(source_id="test-src").observe(1.23)
    # Accessing _sum to verify observation was recorded
    total = metrics.ingestion_duration.labels(source_id="test-src")._sum.get()
    assert total >= 1.23


def test_active_jobs_gauge_set():
    """The active_jobs gauge can be set and read."""
    metrics.active_jobs.labels(job_type="ingest").set(5)
    assert metrics.active_jobs.labels(job_type="ingest")._value.get() == 5


def test_celery_queue_depth_gauge():
    """The celery_queue_depth gauge can be set and read."""
    metrics.celery_queue_depth.labels(queue="default").set(42)
    assert metrics.celery_queue_depth.labels(queue="default")._value.get() == 42


def test_metrics_endpoint_includes_custom_metrics():
    """GET /metrics output includes our custom metric names."""
    client = TestClient(app)
    resp = client.get("/metrics")
    body = resp.text
    assert "osint_events_ingested_total" in body
    assert "osint_alerts_fired_total" in body
    assert "osint_ingestion_duration_seconds" in body
    assert "osint_active_jobs" in body
    assert "osint_celery_queue_depth" in body
