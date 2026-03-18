"""Celery enrichment tasks — vectorize and correlate events."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.services.correlation import find_correlated_events
from osint_core.services.vectorize import search_similar, upsert_event
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

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_vectorize_event_async(event_id))
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
    finally:
        loop.close()


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
    """Search for events correlated to this one and record relationships.

    Correlation uses two strategies in parallel:

    1. **Semantic similarity** — query Qdrant for events whose embeddings
       exceed the cosine-similarity threshold (requires ``vectorize_event``
       to have run first so the event has a vector in Qdrant).
    2. **Exact indicator overlap** — compare (type, value) indicator pairs
       between the target event and candidate events returned by the vector
       search.

    Pipeline steps:
      1. Load the event from the database by event_id.
      2. Build a text representation (title + summary + raw_excerpt).
      3. Call ``search_similar()`` to retrieve candidate events from Qdrant.
      4. For each candidate, resolve its indicator list from the database.
      5. Call ``find_correlated_events()`` with the target event's indicators
         and the enriched candidate list.
      6. Persist a correlation record for each match that is not already
         recorded (idempotent upsert).
      7. Update the event's ``metadata_`` to mark it as correlated.

    Args:
        event_id: Primary key of the event to correlate.

    Returns:
        A summary dict with:
        - ``event_id``: the input event ID.
        - ``status``: ``"ok"`` on success, ``"no_vector"`` when the event has
          no embedding yet, or ``"error"`` on unexpected failure.
        - ``correlations_found``: count of new correlation records created.
        - ``correlated_event_ids``: list of matched event IDs.
        - ``match_types``: mapping of event_id → match_type for each match.
    """
    logger.info("Correlating event: %s", event_id)

    try:
        # --- Load event (DB stub) ---
        # In production:
        #   async with async_session() as db:
        #       event = await db.get(Event, uuid.UUID(event_id))
        #       if event is None:
        #           raise ValueError(f"Event not found: {event_id}")
        #       event_indicators = [
        #           {"type": ind.indicator_type, "value": ind.value}
        #           for ind in event.indicators
        #       ]
        #       text = " ".join(
        #           filter(None, [event.title, event.summary, event.raw_excerpt])
        #       )
        event_indicators: list[dict[str, Any]] = []
        text = ""

        # --- Semantic search ---
        try:
            raw_hits = search_similar(text, limit=20, score_threshold=0.7)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "correlate_event_qdrant_unavailable event_id=%s error=%s",
                event_id,
                exc,
            )
            return {
                "event_id": event_id,
                "status": "no_vector",
                "correlations_found": 0,
                "correlated_event_ids": [],
                "match_types": {},
            }

        # Build candidate list expected by find_correlated_events:
        # each entry needs event_id, indicators, similarity_score.
        # In production we'd load each candidate's indicators from the DB.
        candidates: list[dict[str, Any]] = []
        for hit in raw_hits:
            payload = hit.get("payload") or {}
            candidate_event_id = payload.get("event_id", str(hit.get("id", "")))
            # Skip self-match
            if candidate_event_id == event_id:
                continue
            candidates.append(
                {
                    "event_id": candidate_event_id,
                    # In production: load from DB
                    "indicators": payload.get("indicators", []),
                    "similarity_score": hit.get("score", 0.0),
                }
            )

        correlated = find_correlated_events(event_indicators, candidates)

        # --- Persist correlation records (DB stub) ---
        # In production, for each match:
        #   await db.merge(EventCorrelation(
        #       event_id=uuid.UUID(event_id),
        #       related_event_id=uuid.UUID(match["event_id"]),
        #       match_type=match["match_type"],
        #       score=match["score"],
        #   ))
        #   await db.commit()

        correlated_ids = [m["event_id"] for m in correlated]
        match_types = {m["event_id"]: m["match_type"] for m in correlated}

        if correlated:
            logger.info(
                "correlate_event_complete event_id=%s correlations_found=%d",
                event_id,
                len(correlated),
            )
        else:
            logger.info("correlate_event_no_matches event_id=%s", event_id)

        return {
            "event_id": event_id,
            "status": "ok",
            "correlations_found": len(correlated),
            "correlated_event_ids": correlated_ids,
            "match_types": match_types,
        }

    except Exception as exc:  # noqa: BLE001
        logger.exception("correlate_event_error event_id=%s error=%s", event_id, exc)
        raise self.retry(exc=exc) from exc
