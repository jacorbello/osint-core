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

# --- Report pipeline metrics ---

report_generation_duration_seconds = Histogram(
    "osint_report_generation_duration_seconds",
    "Time to generate a prospecting report end-to-end",
)

report_leads_total = Gauge(
    "osint_report_leads_total",
    "Lead counts per report generation cycle",
    ["stage"],
)

report_email_total = Counter(
    "osint_report_email_total",
    "Email delivery outcomes for prospecting reports",
    ["outcome"],
)

report_generation_total = Counter(
    "osint_report_generation_total",
    "Report generation outcomes",
    ["outcome"],
)
