"""Celery scoring tasks — compute and persist event relevance scores."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.models.plan import PlanVersion
from osint_core.services.scoring import ScoringConfig, score_event, score_to_severity
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


_DEFAULT_HALF_LIFE = 24.0
_DEFAULT_IOC_BOOST = 1.0


def _resolve(section: dict[str, Any], fallback: dict[str, Any], key: str, default: Any) -> Any:
    """Return the first non-None value from section, fallback, then default."""
    if section.get(key) is not None:
        return section[key]
    if fallback.get(key) is not None:
        return fallback[key]
    return default


def _build_scoring_config(plan_content: dict[str, Any]) -> ScoringConfig:
    """Build a ScoringConfig from a plan's content dict.

    Uses explicit ``is not None`` checks so that valid falsy values (e.g.
    ``ioc_match_boost: 0.0``, empty ``source_reputation: {}``) are preserved
    rather than silently replaced by defaults.
    """
    scoring_section = plan_content.get("scoring", {})
    defaults = plan_content.get("defaults", {}).get("scoring", {})

    half_life = float(_resolve(scoring_section, defaults, "recency_half_life_hours", _DEFAULT_HALF_LIFE))
    if half_life <= 0:
        logger.warning(
            "build_scoring_config: recency_half_life_hours=%s is not positive; "
            "falling back to default %s",
            half_life,
            _DEFAULT_HALF_LIFE,
        )
        half_life = _DEFAULT_HALF_LIFE

    source_reputation = _resolve(scoring_section, defaults, "source_reputation", {})
    ioc_match_boost = float(_resolve(scoring_section, defaults, "ioc_match_boost", _DEFAULT_IOC_BOOST))

    return ScoringConfig(
        recency_half_life_hours=half_life,
        source_reputation=source_reputation,
        ioc_match_boost=ioc_match_boost,
    )


async def _score_event_async(event_id: str) -> dict[str, Any]:
    """Score a single event against the active plan for that event's plan version."""
    async with async_session() as db:
        # Load the event
        result = await db.execute(select(Event).where(Event.id == event_id))
        event: Event | None = result.scalar_one_or_none()
        if event is None:
            logger.warning("score_event: event not found: %s", event_id)
            return {"event_id": event_id, "status": "not_found"}

        # Prefer the currently active plan version for the event's plan so that
        # rescore operations reflect the latest scoring config.  Only fall back
        # to the stored plan_version_id when no active version exists for that
        # plan, and fall back to any active plan as a last resort.
        plan: PlanVersion | None = None

        if event.plan_version_id is not None:
            # Find the plan_id this event's version belongs to, then load the
            # active version of that same plan.
            pv_result = await db.execute(
                select(PlanVersion).where(PlanVersion.id == event.plan_version_id)
            )
            stored_version: PlanVersion | None = pv_result.scalar_one_or_none()
            if stored_version is not None:
                active_result = await db.execute(
                    select(PlanVersion)
                    .where(
                        PlanVersion.plan_id == stored_version.plan_id,
                        PlanVersion.is_active.is_(True),
                    )
                    .limit(1)
                )
                plan = active_result.scalar_one_or_none()
                # If the plan has no active version, fall back to the stored one
                if plan is None:
                    plan = stored_version

        if plan is None:
            # Fall back to any active plan
            pv_result = await db.execute(
                select(PlanVersion).where(PlanVersion.is_active.is_(True)).limit(1)
            )
            plan = pv_result.scalar_one_or_none()

        if plan is None:
            logger.warning("score_event: no active plan found for event %s", event_id)
            return {"event_id": event_id, "status": "no_plan"}

        config = _build_scoring_config(plan.content)

        indicator_count = len(event.indicators) if event.indicators else 0
        occurred_at = event.occurred_at or event.ingested_at

        computed_score = score_event(
            source_id=event.source_id,
            occurred_at=occurred_at,
            indicator_count=indicator_count,
            matched_topics=[],
            config=config,
        )

        severity = score_to_severity(computed_score)

        event.score = computed_score
        event.severity = severity
        await db.commit()

        logger.info(
            "scored_event event_id=%s score=%.4f severity=%s",
            event_id, computed_score, severity,
        )
        return {
            "event_id": event_id,
            "score": computed_score,
            "severity": severity,
            "status": "scored",
        }


@celery_app.task(bind=True, name="osint.score_event", max_retries=3)  # type: ignore[untyped-decorator]
def score_event_task(self: Any, event_id: str) -> dict[str, Any]:
    """Score a single event by its ID.

    Pipeline steps:
      1. Load the event from the database
      2. Load the active plan's scoring config
      3. Call score_event() with event metadata
      4. Map score to severity via score_to_severity()
      5. Update the event record with score + severity
    """
    try:
        return asyncio.run(_score_event_async(event_id))
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown) from exc


_RESCORE_BATCH_SIZE = 500


async def _rescore_all_async(plan_id: str | None = None) -> dict[str, Any]:
    """Enqueue score_event_task for all events, optionally filtered by plan.

    Events are fetched in batches of ``_RESCORE_BATCH_SIZE`` to avoid loading
    the entire events table into memory at once.
    """
    total_enqueued = 0
    offset = 0

    while True:
        async with async_session() as db:
            stmt = select(Event.id).order_by(Event.id).offset(offset).limit(_RESCORE_BATCH_SIZE)
            if plan_id is not None:
                stmt = stmt.join(
                    PlanVersion, Event.plan_version_id == PlanVersion.id
                ).where(PlanVersion.plan_id == plan_id)

            result = await db.execute(stmt)
            batch = [str(row[0]) for row in result.fetchall()]

        if not batch:
            break

        for event_id in batch:
            score_event_task.delay(event_id)

        total_enqueued += len(batch)
        offset += len(batch)

        if len(batch) < _RESCORE_BATCH_SIZE:
            break

    logger.info("rescore_all: enqueued %d events", total_enqueued)
    return {"enqueued": total_enqueued}


@celery_app.task(name="osint.rescore_all_events")  # type: ignore[untyped-decorator]
def rescore_all_events_task(plan_id: str | None = None) -> dict[str, Any]:
    """Re-score all existing events against the current active plan.

    Iterates all events in the database and enqueues a score_event_task for
    each one. Optionally filtered to events belonging to a specific plan_id.
    """
    return asyncio.run(_rescore_all_async(plan_id))
