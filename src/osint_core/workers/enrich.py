"""Celery enrichment tasks — vectorize and correlate events."""

from __future__ import annotations

import logging

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.vectorize_event", max_retries=3)
def vectorize_event_task(self, event_id: str) -> dict:
    """Embed event text and upsert to Qdrant.

    Pipeline steps:
      1. Load the event from the database by event_id
      2. Build text representation (title + description + raw content)
      3. Call upsert_event() to embed and store in Qdrant
      4. Mark event as vectorized in the database

    Returns a summary dict with the event_id and status.

    Note: Full DB integration is deferred until the database layer is
    connected.  This task currently serves as the registered entry point
    for the vectorization pipeline.
    """
    logger.info("Vectorizing event: %s", event_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load event from DB by event_id
    # 2. Build text = f"{event.title} {event.description} {event.raw_content}"
    # 3. Build payload = {"title": event.title, "source": event.source_id, ...}
    # 4. Call upsert_event(event_id, text, payload)
    # 5. Update event.vectorized = True in DB

    return {
        "event_id": event_id,
        "status": "stub",
        "vectorized": False,
    }


@celery_app.task(bind=True, name="osint.correlate_event", max_retries=3)
def correlate_event_task(self, event_id: str) -> dict:
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
