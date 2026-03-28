"""Celery tasks for prospecting lead matching after event enrichment."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.services.lead_matcher import LeadMatcher, LeadMatcherConfig
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_CAL_PLAN_ID = "cal-prospecting"


def _build_matcher_config(plan_content: dict[str, Any], plan_id: str) -> LeadMatcherConfig:
    """Build a LeadMatcherConfig from plan content."""
    scoring = plan_content.get("scoring", {})
    return LeadMatcherConfig(
        plan_id=plan_id,
        source_reputation=scoring.get("source_reputation", {}),
    )


async def _match_leads_async(event_ids: list[str], plan_id: str) -> dict[str, Any]:
    """Process a batch of events through lead matching."""
    results: dict[str, str] = {}
    errors: list[str] = []

    async with async_session() as db:
        # Load events — convert string IDs to UUID for the IN clause
        uuid_ids = [uuid_mod.UUID(eid) for eid in event_ids]
        stmt = select(Event).where(Event.id.in_(uuid_ids))
        result = await db.execute(stmt)
        events = list(result.scalars().all())

        if not events:
            logger.warning("match_leads: no events found for ids=%s", event_ids)
            return {"status": "no_events", "results": {}}

        # Build config from first event's plan
        plan_content: dict[str, Any] = {}
        for event in events:
            if event.plan_version:
                plan_content = event.plan_version.content or {}
                break

        config = _build_matcher_config(plan_content, plan_id)
        matcher = LeadMatcher(config)

        for event in events:
            try:
                lead = await matcher.match_event_to_lead(event, db)
                if lead is not None:
                    action = "created" if len(lead.event_ids) == 1 else "updated"
                    results[str(event.id)] = action
                    logger.info(
                        "match_leads: %s lead lead_id=%s event_id=%s",
                        action, lead.id, event.id,
                    )
                else:
                    results[str(event.id)] = "skipped"
                    logger.info(
                        "match_leads: skipped (below threshold) event_id=%s",
                        event.id,
                    )
            except Exception:
                logger.exception(
                    "match_leads: error processing event %s", event.id,
                )
                errors.append(str(event.id))
                results[str(event.id)] = "error"

        await db.commit()

    return {
        "status": "completed",
        "plan_id": plan_id,
        "total": len(events),
        "results": results,
        "errors": errors,
    }


@celery_app.task(bind=True, name="osint.match_leads", max_retries=2)  # type: ignore[untyped-decorator]
def match_leads_task(self: Any, event_ids: list[str], plan_id: str) -> dict[str, Any]:
    """Match enriched events to leads for a prospecting plan.

    Called with event IDs and plan_id after NLP enrichment completes.
    Pipeline chaining is handled by the caller (e.g. ingest worker).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_match_leads_async(event_ids, plan_id))
    except Exception as exc:
        logger.exception("Lead matching failed for events %s", event_ids)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 900),
        ) from exc
    finally:
        loop.close()
