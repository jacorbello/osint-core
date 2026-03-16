"""Celery scoring tasks — compute and persist event relevance scores."""

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
from osint_core.services.scoring import (
    ScoringConfig,
    match_keywords,
    score_event,
    score_to_severity,
)
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Severity levels ordered by ascending severity
_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]

# Default scoring config when no plan config is available
_DEFAULT_SCORING_CONFIG = ScoringConfig(
    recency_half_life_hours=48,
    ioc_match_boost=2.0,
)

_RESCORE_BATCH_SIZE = 500
_DEFAULT_HALF_LIFE = 24.0
_DEFAULT_IOC_BOOST = 1.0


def _severity_gte(a: str, b: str) -> bool:
    """Return True if severity a >= severity b."""
    try:
        return _SEVERITY_ORDER.index(a) >= _SEVERITY_ORDER.index(b)
    except ValueError:
        return False


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

    half_life = float(
        _resolve(scoring_section, defaults, "recency_half_life_hours", _DEFAULT_HALF_LIFE)
    )
    if half_life <= 0:
        logger.warning(
            "build_scoring_config: recency_half_life_hours=%s is not positive; "
            "falling back to default %s",
            half_life,
            _DEFAULT_HALF_LIFE,
        )
        half_life = _DEFAULT_HALF_LIFE

    source_reputation = _resolve(scoring_section, defaults, "source_reputation", {})
    ioc_match_boost = float(
        _resolve(scoring_section, defaults, "ioc_match_boost", _DEFAULT_IOC_BOOST)
    )

    return ScoringConfig(
        recency_half_life_hours=half_life,
        source_reputation=source_reputation,
        ioc_match_boost=ioc_match_boost,
        keywords=plan_content.get("keywords", []),
        keyword_miss_penalty=_resolve(scoring_section, defaults, "keyword_miss_penalty", 0.05),
        target_geo=plan_content.get("target_geo"),
    )


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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_score_event_async(event_id))
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        loop.close()


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

        # Step 2: Resolve scoring config from the active plan version.
        # Prefer the currently active version of the event's associated plan so
        # that rescore operations reflect the latest config.  Fall back to the
        # stored plan_version_id, then any active plan as a last resort.
        from osint_core.models.plan import PlanVersion  # noqa: PLC0415

        plan: PlanVersion | None = None

        if event.plan_version_id is not None:
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
                if plan is None:
                    plan = stored_version

        if plan is None:
            pv_result = await db.execute(
                select(PlanVersion).where(PlanVersion.is_active.is_(True)).limit(1)
            )
            plan = pv_result.scalar_one_or_none()

        if plan is not None:
            scoring_config = _build_scoring_config(plan.content)
            plan_content = plan.content
        else:
            logger.warning("score_event: no active plan found for event %s", event_id)
            scoring_config = _DEFAULT_SCORING_CONFIG
            plan_content = {}

        # Step 3: Compute score
        occurred_at = event.occurred_at or event.ingested_at
        indicator_count = len(event.indicators) if event.indicators else 0

        event_text = " ".join(
            s
            for s in [event.title, event.summary, event.nlp_summary]
            if isinstance(s, str) and s
        )
        matched = match_keywords(event_text, scoring_config.keywords)

        computed_score = score_event(
            source_id=event.source_id,
            occurred_at=occurred_at,
            indicator_count=indicator_count,
            matched_keywords=len(matched),
            total_keywords=len(scoring_config.keywords),
            config=scoring_config,
            country_code=event.country_code,
            lat=event.latitude,
            lon=event.longitude,
            nlp_relevance=event.nlp_relevance,
            corroboration_count=event.corroboration_count,
        )

        # Step 4: Map to severity label, then apply promotion rules
        severity = score_to_severity(computed_score)
        severity = _apply_promotions(event, severity, plan_content)

        # Step 5: Persist score and severity
        event.score = computed_score
        event.severity = severity
        await db.commit()

        logger.info(
            "scored_event event_id=%s score=%.4f severity=%s",
            event_id,
            computed_score,
            severity,
        )

        # Step 6: Evaluate alert rules and chain notify for matched rules
        from osint_core.services.alert_rules import evaluate_rules, parse_rules_from_plan  # noqa: PLC0415

        rules = parse_rules_from_plan(plan_content)
        matched_rules = evaluate_rules(event, rules)
        alert_id: str | None = None
        if matched_rules:
            alert_id = await _create_alert(db, event, severity, computed_score)

    if alert_id and matched_rules:
        from osint_core.workers.notify import send_notification  # avoid circular import

        send_notification.delay(
            alert_id,
            [
                {
                    "name": r.name,
                    "channels": r.channels,
                    "cooldown_minutes": r.cooldown_minutes,
                }
                for r in matched_rules
            ],
        )
        logger.info("Chained send_notification for alert %s", alert_id)

    return {
        "event_id": event_id,
        "score": computed_score,
        "severity": severity,
    }


def _apply_promotions(event: Any, base_severity: str, plan_content: dict[str, Any]) -> str:
    """Apply severity promotion rules from plan, returning the highest promoted severity."""
    promotions = plan_content.get("scoring", {}).get("severity_promotions", [])
    best = base_severity
    for rule in promotions:
        cond = rule.get("condition", {})
        target = rule.get("promote_to", base_severity)
        if _evaluate_condition(event, cond) and _severity_gte(target, best):
            best = target
    return best


def _evaluate_condition(event: Any, condition: dict[str, Any]) -> bool:
    """Evaluate a single promotion condition against an event."""
    field = condition.get("field", "")
    op = condition.get("op", "eq")
    value = condition.get("value")
    actual = _get_field_value(event, field)
    if actual is None:
        return False
    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "gte":
        return actual >= value
    if op == "lte":
        return actual <= value
    if op == "gt":
        return actual > value
    if op == "lt":
        return actual < value
    if op == "contains":
        return str(value).lower() in str(actual).lower()
    if op == "in":
        return actual in value
    return False


def _get_field_value(event: Any, field: str) -> Any:
    """Extract a field value from an event for condition evaluation."""
    if field == "source_id":
        return event.source_id
    if field == "source_category":
        return event.source_category
    if field == "country_code":
        return event.country_code
    if field == "event_type":
        return event.event_type
    if field == "severity":
        return event.severity
    if field == "fatalities":
        return getattr(event, "fatalities", None)
    if field.startswith("indicators."):
        subfield = field.split(".", 1)[1]
        for ind in event.indicators:
            val = getattr(ind, subfield, None) or (ind.metadata_ or {}).get(subfield)
            if val is not None:
                return val
    return None


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


async def _rescore_all_async(plan_id: str | None = None) -> dict[str, Any]:
    """Enqueue score_event_task for all events, optionally filtered by plan.

    Events are fetched in batches of ``_RESCORE_BATCH_SIZE`` to avoid loading
    the entire events table into memory at once.
    """
    from osint_core.models.plan import PlanVersion  # noqa: PLC0415

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

        for eid in batch:
            score_event_task.delay(eid)

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
