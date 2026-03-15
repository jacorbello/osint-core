"""Celery scoring task — compute and persist event relevance scores."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.alert import Alert
from osint_core.models.event import Event
from osint_core.services.scoring import ScoringConfig, score_event, score_to_severity
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Severity levels ordered by ascending severity
_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]

# Default scoring config when no plan config is available
_DEFAULT_SCORING_CONFIG = ScoringConfig(
    recency_half_life_hours=48,
    ioc_match_boost=2.0,
)


def _severity_gte(a: str, b: str) -> bool:
    """Return True if severity a >= severity b."""
    try:
        return _SEVERITY_ORDER.index(a) >= _SEVERITY_ORDER.index(b)
    except ValueError:
        return False


def _chain_notify(event_id: str, event_data: dict[str, Any]) -> None:
    """Fire send_notification as a follow-up task (import deferred to avoid circular)."""
    from osint_core.workers.notify import send_notification  # noqa: PLC0415

    send_notification.delay(event_id, event_data)


@celery_app.task(bind=True, name="osint.score_event", max_retries=3)  # type: ignore[untyped-decorator]
def score_event_task(self: Any, event_id: str) -> dict[str, Any]:
    """Score a single event by its ID.

    Pipeline steps:
      1. Load the event from the database
      2. Load the active plan's scoring config
      3. Call score_event() with event metadata
      4. Map score to severity via score_to_severity()
      5. Update the event record with score + severity
      6. If severity meets force_alert threshold, create an Alert and chain
         the send_notification task

    Returns a dict with event_id, score, and severity.
    """
    logger.info("Scoring event: %s", event_id)
    try:
        return asyncio.run(_score_event_async(event_id))
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown) from exc


async def _score_event_async(event_id: str) -> dict[str, Any]:
    """Async implementation of the scoring pipeline."""
    async with async_session() as db:
        # Step 1: Load event
        result = await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
        event: Event | None = result.scalar_one_or_none()

        if event is None:
            logger.warning("score_event: event not found: %s", event_id)
            return {
                "event_id": event_id,
                "score": None,
                "severity": None,
                "status": "not_found",
            }

        # Step 2: Load scoring config from the event's plan
        scoring_config = _DEFAULT_SCORING_CONFIG
        force_alert_min_severity: str | None = None

        if event.plan_version_id is not None:
            from osint_core.models.plan import PlanVersion as PlanVersionModel
            pv_result = await db.execute(
                select(PlanVersionModel).where(
                    PlanVersionModel.id == event.plan_version_id
                )
            )
            plan = pv_result.scalar_one_or_none()
            if plan:
                plan_scoring = plan.content.get("scoring", {})
                if plan_scoring:
                    scoring_config = ScoringConfig(
                        recency_half_life_hours=plan_scoring.get(
                            "recency_half_life_hours", 48
                        ),
                        source_reputation=plan_scoring.get("source_reputation", {}),
                        ioc_match_boost=plan_scoring.get("ioc_match_boost", 2.0),
                    )
                    force_alert_cfg = plan_scoring.get("force_alert", {})
                    force_alert_min_severity = force_alert_cfg.get("min_severity")

        # Step 3: Compute score
        occurred_at = event.occurred_at or event.ingested_at
        indicator_count = len(event.indicators) if event.indicators else 0

        computed_score = score_event(
            source_id=event.source_id,
            occurred_at=occurred_at,
            indicator_count=indicator_count,
            matched_topics=[],
            config=scoring_config,
        )

        # Step 4: Map to severity label
        severity = score_to_severity(computed_score)

        # Step 5: Persist score and severity
        event.score = computed_score
        event.severity = severity
        await db.commit()

        logger.info(
            "Scored event %s: score=%.4f severity=%s",
            event_id,
            computed_score,
            severity,
        )

        # Step 6: Create alert and chain notify if severity meets threshold
        alert_id: str | None = None
        if force_alert_min_severity and _severity_gte(severity, force_alert_min_severity):
            alert_id = await _create_alert(db, event, severity, computed_score)

    if alert_id:
        from osint_core.workers.notify import send_notification  # avoid circular import
        send_notification.delay(alert_id)
        logger.info("Chained send_notification for alert %s", alert_id)

    result: dict[str, Any] = {
        "event_id": event_id,
        "score": computed_score,
        "severity": severity,
    }


async def _create_alert(
    db: Any,
    event: Event,
    severity: str,
    score: float,
) -> str:
    """Create an Alert record for a high-severity event.

    Returns the alert's string ID.
    """
    fingerprint = hashlib.sha256(
        f"score_event:{event.id}:{severity}".encode()
    ).hexdigest()

    # Check for an existing open alert with the same fingerprint
    result = await db.execute(
        select(Alert).where(Alert.fingerprint == fingerprint, Alert.status == "open")
    )
    existing: Alert | None = result.scalar_one_or_none()
    if existing is not None:
        existing.last_fired_at = datetime.now(UTC)
        existing.occurrences = existing.occurrences + 1
        await db.commit()
        return str(existing.id)

    alert = Alert(
        fingerprint=fingerprint,
        severity=severity,
        title=event.title or f"Scored event: {event.source_id}",
        summary=(
            f"Event scored {score:.2f} ({severity}) from source {event.source_id}."
        ),
        event_ids=[event.id],
        indicator_ids=[ind.id for ind in (event.indicators or [])],
        entity_ids=[ent.id for ent in (event.entities or [])],
        plan_version_id=event.plan_version_id,
        first_fired_at=datetime.now(UTC),
        last_fired_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    return str(alert.id)
