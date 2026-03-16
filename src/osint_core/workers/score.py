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


def _build_scoring_config(plan_content: dict[str, Any]) -> ScoringConfig:
    """Build a ScoringConfig from a plan's content dict."""
    scoring_section = plan_content.get("scoring", {})
    defaults = plan_content.get("defaults", {}).get("scoring", {})

    half_life = (
        scoring_section.get("recency_half_life_hours")
        or defaults.get("recency_half_life_hours")
        or 24.0
    )
    source_reputation = (
        scoring_section.get("source_reputation")
        or defaults.get("source_reputation")
        or {}
    )
    ioc_match_boost = (
        scoring_section.get("ioc_match_boost")
        or defaults.get("ioc_match_boost")
        or 1.0
    )

    return ScoringConfig(
        recency_half_life_hours=float(half_life),
        source_reputation=source_reputation,
        ioc_match_boost=float(ioc_match_boost),
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

        # Load the plan version associated with this event, or find the active plan
        plan: PlanVersion | None = None
        if event.plan_version_id is not None:
            pv_result = await db.execute(
                select(PlanVersion).where(PlanVersion.id == event.plan_version_id)
            )
            plan = pv_result.scalar_one_or_none()

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


async def _rescore_all_async(plan_id: str | None = None) -> dict[str, Any]:
    """Enqueue score_event_task for all events, optionally filtered by plan."""
    async with async_session() as db:
        stmt = select(Event.id)
        if plan_id is not None:
            # Filter to events whose plan_version belongs to the given plan_id
            stmt = stmt.join(
                PlanVersion, Event.plan_version_id == PlanVersion.id
            ).where(PlanVersion.plan_id == plan_id)

        result = await db.execute(stmt)
        event_ids = [str(row[0]) for row in result.fetchall()]

    for event_id in event_ids:
        score_event_task.delay(event_id)

    logger.info("rescore_all: enqueued %d events", len(event_ids))
    return {"enqueued": len(event_ids)}


@celery_app.task(name="osint.rescore_all_events")  # type: ignore[untyped-decorator]
def rescore_all_events_task(plan_id: str | None = None) -> dict[str, Any]:
    """Re-score all existing events against the current active plan.

    Iterates all events in the database and enqueues a score_event_task for
    each one. Optionally filtered to events belonging to a specific plan_id.
    """
    return asyncio.run(_rescore_all_async(plan_id))
