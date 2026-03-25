"""Celery application and Beat configuration."""

import asyncio
import time

import structlog
from celery import Celery
from celery.beat import PersistentScheduler
from celery.schedules import crontab
from celery.signals import worker_process_init

from osint_core.config import settings

logger = structlog.get_logger()

celery_app = Celery(
    "osint-core",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "osint_core.workers.ingest",
        "osint_core.workers.enrich",
        "osint_core.workers.score",
        "osint_core.workers.notify",
        "osint_core.workers.digest",
        "osint_core.workers.nlp_enrich",
        "osint_core.workers.retention",
    ],
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
    beat_scheduler="osint_core.workers.celery_app:PlanScheduler",
    task_routes={
        # Route by registered task name (not module path) since tasks
        # use custom name= overrides like "osint.ingest_source".
        "osint.ingest_source": {"queue": "ingest"},
        "osint.vectorize_event": {"queue": "enrich"},
        "osint.semantic_search": {"queue": "enrich"},
        "osint.correlate_event": {"queue": "enrich"},
        "osint.enrich_entities": {"queue": "enrich"},
        "osint.nlp_enrich_event": {"queue": "enrich"},
        "osint.score_event": {"queue": "score"},
        "osint.rescore_all_events": {"queue": "score"},
        "osint.send_notification": {"queue": "notify"},
        "osint.compile_digest": {"queue": "digest"},
        "osint.purge_expired_events": {"queue": "osint"},
    },
)

# Static beat schedule — tasks that run regardless of active plans
celery_app.conf.beat_schedule = {
    "purge-expired-events-daily": {
        "task": "osint.purge_expired_events",
        "schedule": crontab(hour=3, minute=0),  # daily at 03:00 America/Chicago
    },
}

celery_app.autodiscover_tasks(["osint_core.workers"])

_BEAT_SCHEDULE_MAX_RETRIES = 3
_BEAT_SCHEDULE_RETRY_BACKOFF_BASE = 2  # seconds; delay = base ** attempt


async def _fetch_active_plans_schedule() -> dict[str, object]:
    """Query the database for all active plans and build a combined beat schedule."""
    from osint_core.db import async_session
    from osint_core.services.plan_engine import PlanEngine
    from osint_core.services.plan_store import PlanStore

    store = PlanStore()
    engine = PlanEngine()
    schedule: dict[str, object] = {}

    async with async_session() as db:
        active_plans = await store.get_all_active(db)

    if not active_plans:
        logger.warning("beat_no_active_plans", msg="No active plans found; beat schedule is empty")
        return schedule

    for plan_version in active_plans:
        plan_schedule = engine.build_beat_schedule(plan_version.content)
        schedule.update(plan_schedule)
        logger.info(
            "beat_plan_loaded",
            plan_id=plan_version.plan_id,
            version=plan_version.version,
            tasks=len(plan_schedule),
        )

    return schedule


def load_beat_schedule() -> None:
    """Load the active plan schedule into celery_app.conf.beat_schedule.

    Retries up to _BEAT_SCHEDULE_MAX_RETRIES times with exponential backoff.
    Raises on retry exhaustion so that Beat exits non-zero and an orchestrator
    can restart it — intentionally no silent empty-schedule fallback.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _BEAT_SCHEDULE_MAX_RETRIES + 1):
        try:
            schedule = asyncio.run(_fetch_active_plans_schedule())
            celery_app.conf.beat_schedule.update(schedule)
            logger.info(
                "beat_schedule_loaded",
                plan_tasks=len(schedule),
                total_tasks=len(celery_app.conf.beat_schedule),
            )
            return
        except Exception as exc:
            last_exc = exc
            if attempt < _BEAT_SCHEDULE_MAX_RETRIES:
                delay = _BEAT_SCHEDULE_RETRY_BACKOFF_BASE ** attempt
                logger.warning(
                    "beat_schedule_load_retry",
                    attempt=attempt,
                    max_retries=_BEAT_SCHEDULE_MAX_RETRIES,
                    retry_in=delay,
                )
                time.sleep(delay)

    logger.error(
        "beat_schedule_load_failed",
        msg="Failed to load beat schedule after retries; Beat will exit",
    )
    if last_exc is None:
        raise RuntimeError("Unexpected: no exception captured after retries")
    raise last_exc


class PlanScheduler(PersistentScheduler):
    """Custom beat scheduler that loads plan-driven tasks before the shelve merge.

    Celery's ``Service.start()`` accesses ``self.scheduler`` (triggering
    ``PersistentScheduler.__init__`` → ``setup_schedule`` → ``merge_inplace``)
    *before* the ``beat_init`` signal fires.  The old ``beat_init`` handler
    therefore added plan entries to ``conf.beat_schedule`` too late — the shelve
    had already been populated with only the static purge task.

    By overriding ``setup_schedule`` we call ``load_beat_schedule`` at exactly
    the right moment: after the shelve is opened but before ``merge_inplace``
    reads ``conf.beat_schedule``.
    """

    def setup_schedule(self) -> None:
        load_beat_schedule()
        super().setup_schedule()


@worker_process_init.connect  # type: ignore[untyped-decorator]
def on_worker_process_init(sender: object, **kwargs: object) -> None:
    """Signal handler: initialise OpenTelemetry tracing in each worker process."""
    from osint_core.tracing import init_celery_tracing

    init_celery_tracing()
