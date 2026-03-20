"""Celery task for automated data retention cleanup.

Purges expired events based on their plan_version's retention_class:
- ephemeral: purge after 30 days
- standard: purge after 1 year
- evidentiary: retained indefinitely (never deleted)

Associated entities, indicators, and Qdrant vectors are cleaned up
alongside deleted events.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from osint_core.db import async_session
from osint_core.models.audit import AuditLog
from osint_core.models.event import Event
from osint_core.models.plan import PlanVersion
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Retention thresholds per class
RETENTION_THRESHOLDS: dict[str, timedelta | None] = {
    "ephemeral": timedelta(days=30),
    "standard": timedelta(days=365),
    "evidentiary": None,  # never purged
}

BATCH_SIZE = 500


@celery_app.task(
    bind=True,
    name="osint.purge_expired_events",
    max_retries=3,
)  # type: ignore[untyped-decorator]
def purge_expired_events(self: Any) -> dict[str, Any]:
    """Purge events that have exceeded their retention period.

    Wraps the async implementation with loop.run_until_complete().
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_purge_expired_events_async())
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        loop.close()


async def _purge_expired_events_async() -> dict[str, Any]:
    """Async implementation of the retention purge logic."""
    now = datetime.now(UTC)
    total_deleted = 0
    deleted_by_class: dict[str, int] = {}
    purged_event_ids: list[str] = []

    for retention_class, threshold in RETENTION_THRESHOLDS.items():
        if threshold is None:
            # Evidentiary events are never purged
            continue

        cutoff = now - threshold
        count = await _purge_events_by_retention_class(
            retention_class, cutoff, purged_event_ids,
        )
        deleted_by_class[retention_class] = count
        total_deleted += count

    # Remove Qdrant vectors for deleted events
    qdrant_removed = _remove_qdrant_vectors(purged_event_ids)

    # Create audit log entry
    await _create_audit_log(now, total_deleted, deleted_by_class, qdrant_removed)

    logger.info(
        "Retention purge complete",
        extra={
            "total_deleted": total_deleted,
            "deleted_by_class": deleted_by_class,
            "qdrant_removed": qdrant_removed,
        },
    )

    return {
        "status": "ok",
        "total_deleted": total_deleted,
        "deleted_by_class": deleted_by_class,
        "qdrant_removed": qdrant_removed,
    }


async def _purge_events_by_retention_class(
    retention_class: str,
    cutoff: datetime,
    purged_event_ids: list[str],
) -> int:
    """Delete expired events for a given retention class.

    Returns the number of events deleted.
    """
    deleted_count = 0

    async with async_session() as db:
        # Find plan_version IDs with this retention class
        pv_result = await db.execute(
            select(PlanVersion.id).where(
                PlanVersion.retention_class == retention_class,
            )
        )
        plan_version_ids = list(pv_result.scalars().all())

        if not plan_version_ids:
            return 0

        # Find expired events in batches
        while True:
            result = await db.execute(
                select(Event.id)
                .where(
                    Event.plan_version_id.in_(plan_version_ids),
                    Event.ingested_at < cutoff,
                )
                .limit(BATCH_SIZE)
            )
            event_ids = list(result.scalars().all())

            if not event_ids:
                break

            # Collect IDs for Qdrant cleanup
            purged_event_ids.extend(str(eid) for eid in event_ids)

            # Delete events — association tables (event_entities,
            # event_indicators, event_artifacts, watch_events) are
            # cleaned up by DB CASCADE (all FKs use ondelete="CASCADE").
            await db.execute(
                delete(Event).where(Event.id.in_(event_ids))
            )

            await db.commit()
            deleted_count += len(event_ids)

    return deleted_count


def _remove_qdrant_vectors(event_ids: list[str]) -> int:
    """Remove Qdrant vectors for the given event IDs.

    Returns the number of points removed. Failures are logged but
    do not prevent the purge from completing.
    """
    if not event_ids:
        return 0

    try:
        from osint_core.config import settings
        from osint_core.services.vectorize import get_qdrant

        client = get_qdrant()
        # Derive deterministic point IDs the same way upsert_event does
        point_ids = [
            str(uuid.uuid5(uuid.NAMESPACE_URL, eid)) for eid in event_ids
        ]

        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=point_ids,
        )
        logger.info("Removed %d Qdrant vectors", len(point_ids))
        return len(point_ids)

    except Exception:
        logger.exception("Failed to remove Qdrant vectors for purged events")
        return 0


async def _create_audit_log(
    run_time: datetime,
    total_deleted: int,
    deleted_by_class: dict[str, int],
    qdrant_removed: int,
) -> None:
    """Record an audit log entry for this purge run."""
    async with async_session() as db:
        entry = AuditLog(
            action="retention_purge",
            actor="system",
            resource_type="event",
            details={
                "run_time": run_time.isoformat(),
                "total_deleted": total_deleted,
                "deleted_by_class": deleted_by_class,
                "qdrant_removed": qdrant_removed,
            },
        )
        db.add(entry)
        await db.commit()
