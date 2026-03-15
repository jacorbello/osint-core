"""Celery enrichment tasks — vectorize and correlate events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.services.vectorize import upsert_event
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.vectorize_event", max_retries=3)  # type: ignore[untyped-decorator]
def vectorize_event_task(self: Any, event_id: str) -> dict[str, Any]:
    """Embed event text and upsert to Qdrant.

    Pipeline steps:
      1. Load the event from the database by event_id
      2. Build text representation (title + summary)
      3. Call upsert_event() to embed and store in Qdrant
      4. Return a summary dict with event_id, vector_id, and status

    Raises:
        Retry: On transient Qdrant or database failures (up to max_retries).
    """
    logger.info("Vectorizing event: %s", event_id)

    try:
        return asyncio.run(_vectorize_event_async(event_id))
    except _EventNotFoundError as exc:
        logger.error("Event not found for vectorization: %s", event_id)
        return {
            "event_id": event_id,
            "status": "not_found",
            "error": str(exc),
        }
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        logger.warning(
            "Vectorize failed for event %s (attempt %d), retrying in %ds: %s",
            event_id,
            self.request.retries,
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc


class _EventNotFoundError(Exception):
    """Raised when an event cannot be found in the database."""


async def _vectorize_event_async(event_id: str) -> dict[str, Any]:
    """Async implementation: fetch event, embed, upsert to Qdrant."""
    import uuid

    async with async_session() as db:
        result = await db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        )
        event: Event | None = result.scalar_one_or_none()

    if event is None:
        raise _EventNotFoundError(f"No event found with id={event_id}")

    parts = [p for p in (event.title, event.summary) if p]
    text = " ".join(parts) if parts else event_id

    payload: dict[str, Any] = {
        "source_id": event.source_id,
        "event_type": event.event_type,
        "severity": event.severity,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "title": event.title,
    }

    upsert_event(event_id, text, payload)

    import uuid as _uuid

    vector_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, event_id))
    logger.info("Vectorized event %s -> vector %s", event_id, vector_id)
    return {
        "event_id": event_id,
        "vector_id": vector_id,
        "status": "ok",
    }


@celery_app.task(bind=True, name="osint.correlate_event", max_retries=3)  # type: ignore[untyped-decorator]
def correlate_event_task(self: Any, event_id: str) -> dict[str, Any]:
    """Search Qdrant for events similar to this one and record correlations.

    Pipeline steps:
      1. Load the event from the database by event_id
      2. Build text representation
      3. Call search_similar() to find semantically related events
      4. For each match above threshold:
         a. Check if correlation already recorded
         b. Create EventCorrelation record (exact=False, score=cosine)
      5. Also run correlate_exact() for indicator-based matches

    Returns a summary dict with the event_id and correlation count.

    Note: Full DB integration is deferred until the database layer is
    connected.  This task currently serves as the registered entry point
    for the correlation pipeline.
    """
    logger.info("Correlating event: %s", event_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load event from DB
    # 2. Build text representation
    # 3. Call search_similar(text, limit=20, score_threshold=0.7)
    # 4. For each hit, create EventCorrelation if not already linked
    # 5. Also load event indicators and call correlate_exact()
    #    against indicators of existing events
    # 6. Update event.correlated = True in DB

    return {
        "event_id": event_id,
        "status": "stub",
        "correlations_found": 0,
    }
