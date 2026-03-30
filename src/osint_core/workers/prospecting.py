"""Celery tasks for prospecting lead matching, report generation, and scheduling."""

from __future__ import annotations

import asyncio
import logging
import time
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
    custom = plan_content.get("custom", {})

    kwargs: dict[str, Any] = {
        "plan_id": plan_id,
        "source_reputation": scoring.get("source_reputation", {}),
    }

    threshold = custom.get("lead_confidence_threshold")
    if threshold is not None:
        try:
            parsed_threshold = float(threshold)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid lead_confidence_threshold=%r for plan_id=%s; "
                "falling back to default.",
                threshold,
                plan_id,
            )
        else:
            if 0.0 <= parsed_threshold <= 1.0:
                kwargs["confidence_threshold"] = parsed_threshold
            else:
                logger.warning(
                    "Out-of-range lead_confidence_threshold=%r for plan_id=%s; "
                    "expected value between 0.0 and 1.0. Falling back to default.",
                    parsed_threshold,
                    plan_id,
                )

    return LeadMatcherConfig(**kwargs)


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


async def _generate_report_async(attempt: int = 0) -> dict[str, Any]:
    """Generate a prospecting report and send it via email.

    PDF generation and archival are separated from email delivery so that
    a Resend failure does not discard the already-archived PDF or undo
    the lead-status updates performed inside ``generate_report``.
    """
    from osint_core.config import settings
    from osint_core.services.prospecting_report import ProspectingReportGenerator
    from osint_core.services.resend_notifier import ResendNotifier

    start = time.monotonic()

    async with async_session() as db:
        generator = ProspectingReportGenerator()
        result = await generator.generate_report(db)

    if result is None:
        logger.info("prospecting_report_skipped: no new leads")
        return {"status": "skipped", "reason": "no_new_leads"}

    # --- PDF generated & archived, lead statuses updated at this point ---

    recipients_raw = getattr(settings, "resend_recipients", "") or ""
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients:
        logger.warning(
            "prospecting_report_no_recipients: lead_count=%d",
            result.lead_count,
        )
        return {
            "status": "skipped",
            "reason": "no_recipients",
            "lead_count": result.lead_count,
        }

    # Attempt email delivery separately so PDF/lead work is never lost
    try:
        notifier = ResendNotifier()
        executive_summary = (
            f"Report generated with {result.lead_count} leads "
            f"on {result.report_date}."
        )
        sent = await notifier.send_report(
            pdf_bytes=result.pdf_bytes,
            executive_summary=executive_summary,
            recipients=recipients,
        )
    except Exception as email_exc:
        logger.error(
            "report_delivery_failed: plan_id=%s error=%s attempt=%d "
            "lead_count=%d artifact_uri=%s",
            _CAL_PLAN_ID,
            str(email_exc),
            attempt + 1,
            result.lead_count,
            result.artifact_uri,
        )
        raise

    elapsed = time.monotonic() - start
    logger.info(
        "prospecting_report_complete: lead_count=%d artifact_uri=%s "
        "email_sent=%s recipients=%d elapsed=%.2fs",
        result.lead_count, result.artifact_uri, sent,
        len(recipients), elapsed,
    )

    return {
        "status": "completed",
        "lead_count": result.lead_count,
        "artifact_uri": result.artifact_uri,
        "email_sent": sent,
        "elapsed_seconds": round(elapsed, 2),
    }


@celery_app.task(bind=True, name="osint.generate_prospecting_report", max_retries=3)  # type: ignore[untyped-decorator]
def generate_prospecting_report_task(self: Any) -> dict[str, Any]:
    """Generate a prospecting report and email it via Resend.

    Scheduled via Celery beat at 8 AM and 3 PM America/Chicago time.
    Gracefully skips if no new leads exist or no recipients are configured.
    Retries up to 3 times with exponential backoff (60s, 120s, 240s, capped at 300s).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _generate_report_async(attempt=self.request.retries),
        )
    except Exception as exc:
        logger.exception("Prospecting report generation failed")
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 60, 300),
        ) from exc
    finally:
        loop.close()


async def _collect_sources_async(plan_id: str) -> dict[str, Any]:
    """Trigger ingest for all sources in the prospecting plan."""
    from osint_core.services.plan_store import PlanStore

    async with async_session() as db:
        store = PlanStore()
        plan_version = await store.get_active(db, plan_id)

    if plan_version is None:
        logger.warning("collect_sources_no_plan: plan_id=%s", plan_id)
        return {"status": "skipped", "reason": "no_active_plan"}

    content = plan_version.content or {}
    sources = content.get("sources", [])

    if not sources:
        logger.warning("collect_sources_empty: plan_id=%s", plan_id)
        return {"status": "skipped", "reason": "no_sources"}

    from osint_core.workers.ingest import ingest_source

    dispatched = 0
    for source in sources:
        source_id = source.get("id")
        if source_id:
            ingest_source.delay(plan_id=plan_id, source_id=source_id)
            dispatched += 1

    logger.info(
        "collect_sources_dispatched: plan_id=%s source_count=%d",
        plan_id, dispatched,
    )

    return {
        "status": "completed",
        "plan_id": plan_id,
        "sources_dispatched": dispatched,
    }


@celery_app.task(bind=True, name="osint.collect_prospecting_sources", max_retries=1)  # type: ignore[untyped-decorator]
def collect_prospecting_sources_task(self: Any, plan_id: str = _CAL_PLAN_ID) -> dict[str, Any]:
    """Trigger ingest for all CAL prospecting sources.

    Scheduled via Celery beat ~1 hour before report generation (7 AM / 2 PM America/Chicago).
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect_sources_async(plan_id))
    except Exception as exc:
        logger.exception("Prospecting source collection failed")
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 60, 300),
        ) from exc
    finally:
        loop.close()
