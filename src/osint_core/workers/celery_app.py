"""Celery application and Beat configuration."""

import asyncio

import structlog
from celery import Celery
from celery.signals import beat_init

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
    task_routes={
        "osint_core.workers.ingest.*": {"queue": "ingest"},
        "osint_core.workers.enrich.*": {"queue": "enrich"},
        "osint_core.workers.score.*": {"queue": "score"},
        "osint_core.workers.notify.*": {"queue": "notify"},
        "osint_core.workers.digest.*": {"queue": "digest"},
    },
)

# Beat schedule starts empty; populated from active plans via beat_init signal
celery_app.conf.beat_schedule = {}

celery_app.autodiscover_tasks(["osint_core.workers"])


async def _fetch_active_plans_schedule() -> dict:
    """Query the database for all active plans and build a combined beat schedule."""
    from osint_core.db import async_session
    from osint_core.services.plan_engine import PlanEngine
    from osint_core.services.plan_store import PlanStore

    store = PlanStore()
    engine = PlanEngine()
    schedule: dict = {}

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
    """Load the active plan schedule into celery_app.conf.beat_schedule."""
    try:
        schedule = asyncio.run(_fetch_active_plans_schedule())
        celery_app.conf.beat_schedule = schedule
        logger.info("beat_schedule_loaded", total_tasks=len(schedule))
    except Exception:
        logger.exception(
            "beat_schedule_load_failed",
            msg="Failed to load beat schedule from database",
        )
        celery_app.conf.beat_schedule = {}


@beat_init.connect
def on_beat_init(sender, **kwargs):
    """Signal handler: load active plan schedule when Beat starts."""
    load_beat_schedule()
