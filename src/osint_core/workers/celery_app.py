"""Celery application and Beat configuration."""

from celery import Celery

from osint_core.config import settings

celery_app = Celery(
    "osint-core",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Chicago",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="osint",
    task_routes={
        "osint_core.workers.ingest.*": {"queue": "ingest"},
        "osint_core.workers.enrich.*": {"queue": "enrich"},
        "osint_core.workers.score.*": {"queue": "score"},
        "osint_core.workers.notify.*": {"queue": "notify"},
        "osint_core.workers.digest.*": {"queue": "digest"},
    },
)

# Beat schedule is dynamically rebuilt from active plan
celery_app.conf.beat_schedule = {}

celery_app.autodiscover_tasks(["osint_core.workers"])
