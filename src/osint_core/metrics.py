"""Custom Prometheus metrics for OSINT platform business telemetry."""

from prometheus_client import Counter, Gauge, Histogram

events_ingested = Counter(
    "osint_events_ingested_total",
    "Total events ingested",
    ["source_id"],
)

alerts_fired = Counter(
    "osint_alerts_fired_total",
    "Total alerts fired",
    ["severity", "route"],
)

ingestion_duration = Histogram(
    "osint_ingestion_duration_seconds",
    "Time to ingest a source",
    ["source_id"],
)

active_jobs = Gauge(
    "osint_active_jobs",
    "Currently running jobs",
    ["job_type"],
)

celery_queue_depth = Gauge(
    "osint_celery_queue_depth",
    "Celery queue depth",
    ["queue"],
)
