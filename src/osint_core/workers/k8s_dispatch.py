"""Celery task for NER entity enrichment with K8s Job dispatch.

For lightweight events, entity extraction runs in-process via spaCy.
For heavy/batch workloads, a Kubernetes Job is dispatched to wrk-3
(GPU node, tainted NoSchedule) for accelerated NER processing.
"""

from __future__ import annotations

import logging
from typing import Any

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.enrich_entities", max_retries=3)  # type: ignore[untyped-decorator]
def enrich_entities_task(self: Any, event_id: str) -> dict[str, Any]:
    """Extract named entities from an event and persist them.

    Pipeline steps:
      1. Load the event from the database by event_id
      2. Build text representation (title + description + raw content)
      3. Call extract_entities() to run spaCy NER
      4. Persist extracted entities linked to the event
      5. Optionally dispatch K8s Job for GPU-accelerated NER on large text

    K8s Job dispatch (future — for wrk-3 GPU node):
      - Build a Kubernetes Job manifest targeting:
          nodeSelector: { role: batch-compute }
          tolerations: [{ key: gpu, effect: NoSchedule }]
      - Job container runs a dedicated NER image with GPU support
      - Results are written back to the database via shared Postgres
      - Job status is polled or reported via a callback webhook

    Returns a summary dict with the event_id and entity count.

    Note: Full DB integration and K8s dispatch are deferred.  This task
    currently serves as the registered entry point for the NER pipeline.
    """
    logger.info("Enriching entities for event: %s", event_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load event from DB by event_id
    # 2. Build text = f"{event.title} {event.description} {event.raw_content}"
    # 3. Call extract_entities(text) from osint_core.services.ner
    # 4. For each entity:
    #    - Create Entity record (type, name, start, end)
    #    - Link to event via EventEntity association
    # 5. For large text (>10k chars) or batch mode:
    #    - Build K8s Job manifest (see docstring above)
    #    - Submit via kubernetes client: batch_v1.create_namespaced_job()
    #    - Record job reference for status tracking
    # 6. Update event.entities_extracted = True

    return {
        "event_id": event_id,
        "status": "stub",
        "entities_found": 0,
    }
