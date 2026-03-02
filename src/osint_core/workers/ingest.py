"""Celery ingest tasks — fetch items from configured sources and create events."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _dedupe_fingerprint(source_id: str, item_data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint for deduplication."""
    payload = json.dumps({"source": source_id, **item_data}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@celery_app.task(bind=True, name="osint.ingest_source", max_retries=3)  # type: ignore[untyped-decorator]
def ingest_source(self: Any, source_id: str) -> dict[str, Any]:
    """Ingest items from a configured source.

    Pipeline steps:
      1. Load active plan, get source config
      2. Get connector from registry
      3. Fetch items
      4. For each item:
         a. Compute dedupe fingerprint
         b. Check if exists (skip if duplicate)
         c. Create Event
         d. Extract indicators, create/link Indicators
         e. Chain enrichment tasks
      5. Record job in jobs table

    Returns a summary dict with counts of ingested/skipped items.

    Note: Full DB integration is deferred until the database layer is
    connected.  This task currently serves as the registered entry point
    for the ingest pipeline.
    """
    logger.info("Starting ingest for source: %s", source_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load the active plan from the DB/plan store
    # 2. Look up source config by source_id
    # 3. Instantiate the connector via ConnectorRegistry
    # 4. Call connector.fetch() to get RawItems
    # 5. For each item:
    #    - Compute dedupe fingerprint via _dedupe_fingerprint()
    #    - Check DB for existing fingerprint (skip duplicates)
    #    - Create Event record
    #    - Extract indicators via extract_indicators()
    #    - Create/link Indicator records
    #    - Chain score_event_task and enrichment tasks
    # 6. Record a Job entry with results

    return {
        "source_id": source_id,
        "status": "completed",
        "ingested": 0,
        "skipped": 0,
        "errors": 0,
    }
