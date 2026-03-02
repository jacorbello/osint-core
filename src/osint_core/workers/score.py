"""Celery scoring task — compute and persist event relevance scores."""

from __future__ import annotations

import logging

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.score_event", max_retries=3)
def score_event_task(self, event_id: str) -> dict:
    """Score a single event by its ID.

    Pipeline steps:
      1. Load the event from the database
      2. Load the active plan's scoring config
      3. Call score_event() with event metadata
      4. Map score to severity via score_to_severity()
      5. Update the event record with score + severity
      6. If severity meets force_alert threshold, chain alert task

    Returns a summary dict with the computed score and severity.

    Note: Full DB integration is deferred until the database layer is
    connected.  This task currently serves as the registered entry point
    for the scoring pipeline.
    """
    logger.info("Scoring event: %s", event_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load the event by ID from the DB
    # 2. Load ScoringConfig from the active plan
    # 3. Call score_event(source_id, occurred_at, indicator_count, topics, config)
    # 4. Call score_to_severity(score)
    # 5. Update event.score and event.severity in the DB
    # 6. If severity >= force_alert threshold, chain notify task

    return {
        "event_id": event_id,
        "score": None,
        "severity": None,
        "status": "stub",
    }
