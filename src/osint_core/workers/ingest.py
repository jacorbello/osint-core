"""Celery ingest tasks — fetch items from configured sources and create events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osint_core.connectors import registry
from osint_core.connectors.base import SourceConfig
from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from osint_core.services.indicators import extract_indicators
from osint_core.services.plan_store import PlanStore
from osint_core.workers.celery_app import celery_app
from osint_core.workers.enrich import correlate_event_task, vectorize_event_task
from osint_core.workers.score import score_event_task

logger = logging.getLogger(__name__)

plan_store = PlanStore()

ERROR_RATE_THRESHOLD = 0.5


def _dedupe_fingerprint(plan_id: str, source_id: str, item_data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint for deduplication.

    Includes plan_id so that identical items from the same source_id
    across different plans are not incorrectly treated as duplicates.
    """
    payload = json.dumps(
        {"plan": plan_id, "source": source_id, **item_data}, sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


@celery_app.task(bind=True, name="osint.ingest_source", max_retries=3)  # type: ignore[untyped-decorator]
def ingest_source(self: Any, source_id: str, plan_id: str) -> dict[str, Any]:
    """Ingest items from a configured source.

    Wraps the async implementation with asyncio.run().
    Config errors (ValueError, KeyError) are not retried.
    Transient errors are retried with capped exponential backoff.
    """
    try:
        return asyncio.run(_ingest_source_async(self, source_id, plan_id))
    except (ValueError, KeyError) as exc:
        logger.error("Ingest config error for %s: %s", source_id, exc)
        try:
            asyncio.run(_record_failed_job(self, plan_id, source_id, str(exc)))
        except Exception:
            logger.exception("Failed to record failed job for %s", source_id)
        return {
            "source_id": source_id,
            "plan_id": plan_id,
            "status": "failed",
            "error": str(exc),
            "ingested": 0,
            "skipped": 0,
            "errors": 0,
        }
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown) from exc


async def _ingest_source_async(
    task_self: Any,
    source_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Async implementation of the ingest pipeline."""
    ingested = 0
    skipped = 0
    errors = 0
    new_event_ids: list[str] = []
    plan_version_id = None

    async with async_session() as db:
        # Step 1: Resolve plan & source config
        plan = await plan_store.get_active(db, plan_id)
        if not plan:
            raise ValueError(f"No active plan for plan_id={plan_id}")

        plan_version_id = plan.id
        source_cfg_dict = next(
            (s for s in plan.content.get("sources", []) if s["id"] == source_id),
            None,
        )
        if not source_cfg_dict:
            raise ValueError(f"Source {source_id} not in plan {plan_id}")

        source_cfg = SourceConfig(
            id=source_cfg_dict["id"],
            type=source_cfg_dict["type"],
            url=source_cfg_dict.get("url", ""),
            weight=source_cfg_dict.get("weight", 1.0),
            extra=source_cfg_dict.get("params", {}),
        )

        # Step 2: Fetch items
        connector = registry.get(source_cfg.type, source_cfg)
        items = await connector.fetch()
        logger.info("Fetched %d items from %s", len(items), source_id)

        # Step 3: Dedupe & persist each item
        for item in items:
            try:
                fingerprint = _dedupe_fingerprint(plan_id, source_id, item.raw_data)

                # Pre-check for duplicate (fast path)
                result = await db.execute(
                    select(Event.id).where(Event.dedupe_fingerprint == fingerprint)
                )
                if result.scalar_one_or_none() is not None:
                    skipped += 1
                    continue

                async with db.begin_nested():
                    # Create Event
                    event = Event(
                        event_type=source_cfg.type,
                        source_id=source_id,
                        title=item.title,
                        summary=item.summary,
                        raw_excerpt=item.url,
                        occurred_at=item.occurred_at,
                        severity=item.severity,
                        dedupe_fingerprint=fingerprint,
                        metadata_=item.raw_data,
                        plan_version_id=plan.id,
                    )
                    db.add(event)

                    try:
                        async with db.begin_nested():
                            await db.flush()
                    except IntegrityError:
                        skipped += 1
                        continue

                    # Extract and link indicators
                    indicator_dicts = extract_indicators(
                        f"{item.title} {item.summary}"
                    )
                    for ind_dict in indicator_dicts:
                        indicator = await _upsert_indicator(
                            db, ind_dict, source_id
                        )
                        if indicator is not None:
                            event.indicators.append(indicator)

                    new_event_ids.append(str(event.id))
                    ingested += 1

            except Exception:
                logger.exception("Failed to process item from %s", source_id)
                errors += 1

        # Step 4: Error rate check
        if items and errors / len(items) > ERROR_RATE_THRESHOLD:
            raise RuntimeError(
                f"High error rate: {errors}/{len(items)} items failed for {source_id}"
            )

        # Step 5: Commit
        await db.commit()

    # Step 6: Chain downstream tasks
    for event_id in new_event_ids:
        score_event_task.delay(event_id)
        vectorize_event_task.delay(event_id)
        correlate_event_task.delay(event_id)

    # Step 7: Record Job
    if errors > 0 and ingested > 0:
        job_status = "partial_success"
    elif errors > 0:
        job_status = "failed"
    else:
        job_status = "succeeded"

    try:
        await _record_job(
            task_self, plan_version_id, source_id, plan_id,
            job_status, ingested, skipped, errors,
        )
    except Exception:
        logger.exception("Failed to record job for %s", source_id)

    return {
        "source_id": source_id,
        "plan_id": plan_id,
        "status": job_status,
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }


async def _upsert_indicator(
    db: Any,
    ind_dict: dict[str, Any],
    source_id: str,
) -> Indicator | None:
    """Insert or fetch an existing indicator, merging source_id into sources."""
    # Try to find existing
    result = await db.execute(
        select(Indicator).where(
            Indicator.indicator_type == ind_dict["type"],
            Indicator.value == ind_dict["value"],
        )
    )
    indicator: Indicator | None = result.scalar_one_or_none()

    if indicator is not None:
        # Merge source_id if missing
        if source_id not in (indicator.sources or []):
            indicator.sources = [*(indicator.sources or []), source_id]
        return indicator

    # Try insert
    indicator = Indicator(
        indicator_type=ind_dict["type"],
        value=ind_dict["value"],
        sources=[source_id],
    )
    db.add(indicator)
    try:
        async with db.begin_nested():
            await db.flush()
        return indicator
    except IntegrityError:
        # Savepoint rolled back, outer transaction intact
        result = await db.execute(
            select(Indicator).where(
                Indicator.indicator_type == ind_dict["type"],
                Indicator.value == ind_dict["value"],
            )
        )
        found: Indicator | None = result.scalar_one_or_none()
        if found and source_id not in (found.sources or []):
            found.sources = [*(found.sources or []), source_id]
        return found


async def _record_job(
    task_self: Any,
    plan_version_id: Any,
    source_id: str,
    plan_id: str,
    status: str,
    ingested: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> None:
    """Record a Job entry for this ingest run."""
    async with async_session() as db:
        job = Job(
            job_type="ingest",
            status=status,
            celery_task_id=getattr(task_self.request, "id", None),
            plan_version_id=plan_version_id,
            input_params={"source_id": source_id, "plan_id": plan_id},
            output={"ingested": ingested, "skipped": skipped, "errors": errors},
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()


async def _record_failed_job(
    task_self: Any,
    plan_id: str,
    source_id: str,
    error_msg: str,
) -> None:
    """Record a failed Job entry (for config errors that don't retry)."""
    async with async_session() as db:
        job = Job(
            job_type="ingest",
            status="failed",
            celery_task_id=getattr(task_self.request, "id", None),
            input_params={"source_id": source_id, "plan_id": plan_id},
            error=error_msg,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
