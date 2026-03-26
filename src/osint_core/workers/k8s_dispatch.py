"""Celery task for NER entity enrichment with K8s Job dispatch.

For lightweight events, entity extraction runs in-process via spaCy.
For heavy/batch workloads, a Kubernetes Job is dispatched to wrk-3
(GPU node, tainted NoSchedule) for accelerated NER processing.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.entity import Entity
from osint_core.models.event import Event
from osint_core.services.ner import extract_entities
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.enrich_entities", max_retries=3)  # type: ignore[untyped-decorator]
def enrich_entities_task(self: Any, event_id: str) -> dict[str, Any]:
    """Extract named entities from an event and persist them.

    Pipeline steps:
      1. Load the event from the database by event_id
      2. Build text representation (title + summary + raw_excerpt)
      3. Call extract_entities() to run spaCy NER
      4. Upsert Entity records (deduplicate by name + type)
      5. Link entities to the event via the event_entities association table

    K8s Job dispatch (future — for wrk-3 GPU node):
      - Build a Kubernetes Job manifest targeting:
          nodeSelector: { role: batch-compute }
          tolerations: [{ key: gpu, effect: NoSchedule }]
      - Job container runs a dedicated NER image with GPU support
      - Results are written back to the database via shared Postgres
      - Job status is polled or reported via a callback webhook

    Returns a summary dict with the event_id and entity count.
    """
    logger.info("Enriching entities for event: %s", event_id)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_enrich_entities_async(event_id))
    except _EventNotFoundError as exc:
        logger.error("Event not found for entity enrichment: %s", event_id)
        return {
            "event_id": event_id,
            "status": "not_found",
            "entities_found": 0,
            "error": str(exc),
        }
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        logger.warning(
            "Entity enrichment failed for event %s (attempt %d), retrying in %ds: %s",
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


async def _upsert_entity(
    db: Any,
    entity_dict: dict[str, Any],
) -> Entity:
    """Insert or fetch an existing entity, deduplicating by name + type."""
    result = await db.execute(
        select(Entity).where(
            Entity.entity_type == entity_dict["type"],
            Entity.name == entity_dict["name"],
        )
    )
    entity: Entity | None = result.scalar_one_or_none()

    if entity is not None:
        # Update last_seen timestamp
        entity.last_seen = datetime.now(UTC)
        return entity

    # Try insert
    entity = Entity(
        entity_type=entity_dict["type"],
        name=entity_dict["name"],
    )
    db.add(entity)
    try:
        async with db.begin_nested():
            await db.flush()
        return entity
    except Exception:
        # Race condition: another worker inserted the same entity concurrently.
        # Roll back the savepoint and fetch the existing record.
        await db.rollback()
        result = await db.execute(
            select(Entity).where(
                Entity.entity_type == entity_dict["type"],
                Entity.name == entity_dict["name"],
            )
        )
        found: Entity | None = result.scalar_one_or_none()
        if found is not None:
            found.last_seen = datetime.now(UTC)
            return found
        raise


async def _enrich_entities_async(event_id: str) -> dict[str, Any]:
    """Async implementation: fetch event, run NER, upsert entities, link."""
    async with async_session() as db:
        result = await db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        )
        event: Event | None = result.scalar_one_or_none()

        if event is None:
            raise _EventNotFoundError(f"No event found with id={event_id}")

        # Build text from available fields
        parts = [p for p in (event.title, event.summary, event.raw_excerpt) if p]
        text = " ".join(parts)

        if not text.strip():
            logger.info("No text content for event %s, skipping NER", event_id)
            return {
                "event_id": event_id,
                "status": "skipped",
                "entities_found": 0,
            }

        # Run spaCy NER
        raw_entities = extract_entities(text)
        logger.info(
            "Extracted %d raw entities from event %s", len(raw_entities), event_id,
        )

        # Deduplicate extracted entities by (type, name) before persisting
        seen: set[tuple[str, str]] = set()
        unique_entities: list[dict[str, Any]] = []
        for ent in raw_entities:
            key = (ent["type"], ent["name"])
            if key not in seen:
                seen.add(key)
                unique_entities.append(ent)

        # Upsert each entity and link to event.
        # Materialize the selectin-loaded collection into a plain list
        # to avoid re-triggering the lazy loader on each `not in` check
        # and to be safe if this code is ever called on a new Event.
        linked_count = 0
        existing_entities = list(event.entities)
        for ent_dict in unique_entities:
            entity = await _upsert_entity(db, ent_dict)
            if entity not in existing_entities:
                event.entities.append(entity)
                existing_entities.append(entity)
                linked_count += 1

        await db.commit()

    logger.info(
        "Entity enrichment complete for event %s: %d entities linked",
        event_id,
        linked_count,
    )
    return {
        "event_id": event_id,
        "status": "ok",
        "entities_found": linked_count,
    }
