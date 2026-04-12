"""Celery tasks for prospecting lead matching, report generation, and scheduling."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid as uuid_mod
from typing import Any

from sqlalchemy import select

from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.models.lead import Lead
from osint_core.services.deep_analyzer import DeepAnalyzer
from osint_core.services.lead_matcher import LeadMatcher, LeadMatcherConfig
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_CAL_PLAN_ID = "cal-prospecting"

# Email delivery retry settings
_EMAIL_MAX_RETRIES = 3
_EMAIL_BACKOFF_BASE = 2  # seconds; delay = base ** attempt (1-indexed)

# Pipeline completion guard settings
_MATCH_LEADS_TASK_NAME = "osint.match_leads"
_ANALYSIS_TASK_NAME = "osint.analyze_leads"
_GUARD_MAX_DEFERRALS = 5
_GUARD_BACKOFF_BASE = 120  # seconds; delay = base * (attempt + 1), capped at 600


def _source_type_label(source_id: str) -> str:
    """Map source_id prefix to a human-readable source type label."""
    if source_id.startswith("x_"):
        return "social_media"
    if source_id.startswith("rss_"):
        return "news_article"
    if source_id.startswith("univ_"):
        return "policy_document"
    return "unknown"


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

    if custom.get("deep_analysis_enabled"):
        kwargs["deep_analysis_enabled"] = True

    return LeadMatcherConfig(**kwargs)


def _is_deep_analysis_enabled(plan_content: dict[str, Any] | None = None) -> bool:
    """Check if deep analysis is enabled for a plan."""
    if plan_content is None:
        return False
    custom = plan_content.get("custom", {})
    return bool(custom.get("deep_analysis_enabled", False))


def _get_precedent_map(plan_content: dict[str, Any]) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Extract precedent map from plan content."""
    custom: dict[str, Any] = plan_content.get("custom", {})
    result: dict[str, dict[str, list[dict[str, str]]]] = custom.get("precedent_map", {})
    return result


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
        result = loop.run_until_complete(_match_leads_async(event_ids, plan_id))
    except Exception as exc:
        logger.exception("Lead matching failed for events %s", event_ids)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 900),
        ) from exc
    finally:
        loop.close()

    # Dispatch deep analysis after successful lead matching
    analyze_leads_task.delay(plan_id)

    return result


async def _analyze_leads_async(plan_id: str) -> dict[str, Any]:
    """Run deep analysis on all pending leads for a plan."""
    from osint_core.models.plan import PlanVersion

    async with async_session() as db:
        # Load active plan content
        plan_stmt = (
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id, PlanVersion.is_active.is_(True))
            .limit(1)
        )
        plan_result = await db.execute(plan_stmt)
        plan_version = plan_result.scalar_one_or_none()

        if not plan_version:
            return {"status": "skipped", "reason": "no_active_plan"}

        plan_content = plan_version.content or {}

        if not _is_deep_analysis_enabled(plan_content):
            return {"status": "skipped", "reason": "deep_analysis_disabled"}

        custom = plan_content.get("custom", {})
        relevance_gate = bool(custom.get("deep_analysis_relevance_gate", False))
        precedent_map = _get_precedent_map(plan_content)

        # Select pending leads
        stmt = (
            select(Lead)
            .where(
                Lead.plan_id == plan_id,
                Lead.analysis_status == "pending",
            )
        )
        lead_result = await db.execute(stmt)
        leads = list(lead_result.scalars().all())

        if not leads:
            return {"status": "completed", "analyzed": 0, "plan_id": plan_id}

        analyzer = DeepAnalyzer(precedent_map=precedent_map)
        analyzed = 0
        failed = 0

        for lead in leads:
            # Get the first event for source material
            if not lead.event_ids:
                lead.analysis_status = "no_source_material"
                continue

            event_stmt = select(Event).where(Event.id == lead.event_ids[0])
            event_result = await db.execute(event_stmt)
            event = event_result.scalar_one_or_none()

            if not event:
                lead.analysis_status = "no_source_material"
                continue

            # Optional relevance gate
            if relevance_gate:
                relevance = getattr(event, "nlp_relevance", None)
                if isinstance(relevance, str) and relevance.strip().lower() != "relevant":
                    lead.analysis_status = "no_source_material"
                    continue

            # Gather corroborating events from other events linked to this lead
            all_event_ids = lead.event_ids or []
            corroborating_events: list[dict[str, Any]] = []
            if len(all_event_ids) > 1:
                other_ids = [eid for eid in all_event_ids if eid != event.id][:4]
                if other_ids:
                    other_result = await db.execute(
                        select(Event).where(Event.id.in_(other_ids))
                    )
                    for other_evt in other_result.scalars().all():
                        other_meta = other_evt.metadata_ or {}
                        corroborating_events.append({
                            "type": _source_type_label(other_evt.source_id or ""),
                            "title": other_evt.title or "",
                            "url": other_meta.get("url", ""),
                            "summary": (other_evt.raw_excerpt or "")[:500],
                            "date": str(other_evt.created_at),
                        })

            try:
                result = await analyzer.analyze_lead(
                    lead, event, corroborating_events=corroborating_events,
                )
            except Exception as exc:
                logger.warning(
                    "deep_analysis_failed lead_id=%s error=%s",
                    str(lead.id), str(exc),
                )
                lead.analysis_status = "failed"
                failed += 1
                continue

            if result is None:
                lead.analysis_status = "no_source_material"
                continue

            # Check for quality gate failures returned by analyzer
            result_status = result.get("analysis_status", "")
            if result_status in ("no_content", "extraction_failed", "non_english"):
                lead.deep_analysis = result
                lead.analysis_status = result_status
                continue

            lead.deep_analysis = result

            # Update lead title from screening if available
            lead_title = result.get("lead_title")
            if lead_title:
                lead.title = lead_title

            provisions = result.get("provisions", [])

            # Compute severity from provisions
            if provisions:
                lead.severity = DeepAnalyzer.compute_max_severity(provisions)

            # Downgrade non-actionable leads and preserve not_actionable status
            actionable = result.get("actionable", True)
            if not actionable or result_status == "not_actionable":
                lead.severity = "info"
                lead.analysis_status = "not_actionable"
            else:
                lead.analysis_status = "completed"

            # Populate citations
            metadata = event.metadata_ or {}
            legal_precedent: list[dict[str, Any]] = []
            for prov in provisions:
                for case in prov.get("precedent", []):
                    legal_precedent.append(case)

            lead.citations = DeepAnalyzer.build_citations(
                provisions,
                legal_precedent,
                source_url=metadata.get("url", ""),
                document_title=lead.title or "",
                minio_uri=metadata.get("minio_uri", ""),
            )

            analyzed += 1

        await db.commit()

    return {
        "status": "completed",
        "plan_id": plan_id,
        "analyzed": analyzed,
        "failed": failed,
        "total": len(leads),
    }


@celery_app.task(bind=True, name="osint.analyze_leads", max_retries=2)  # type: ignore[untyped-decorator]
def analyze_leads_task(self: Any, plan_id: str) -> dict[str, Any]:
    """Run deep constitutional analysis on pending leads.

    Called after match_leads completes. Analyzes full policy documents
    and incident reports for clause-level constitutional issues.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_analyze_leads_async(plan_id))
    except Exception as exc:
        logger.exception("Deep analysis failed for plan %s", plan_id)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 300),
        ) from exc
    finally:
        loop.close()


_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: str) -> str:
    """Expand ``${VAR}`` placeholders from ``os.environ``.

    Returns the expanded string, or an empty string if the referenced
    environment variable is unset/empty.
    """

    def _replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_VAR_RE.sub(_replace, value)


def _resolve_recipients(plan_content: dict[str, Any] | None) -> list[str]:
    """Return recipients from plan YAML, falling back to global settings.

    Checks ``plan_content["custom"]["resend"]["recipients"]`` first.
    Each entry may contain ``${VAR}`` placeholders that are expanded from
    environment variables.  A single env var value may contain multiple
    comma-separated addresses.  If the resolved list is empty (e.g. all
    env vars are unset), falls back to the comma-separated
    ``settings.resend_recipients`` value.
    """
    from osint_core.config import settings

    # Try plan-level recipients first
    if plan_content:
        plan_recipients_raw: list[str] = (
            plan_content.get("custom", {}).get("resend", {}).get("recipients", [])
        )
        resolved: list[str] = []
        for raw in plan_recipients_raw:
            if not raw:
                continue
            expanded = _expand_env_vars(raw)
            # Support comma-separated values within a single env var
            for part in expanded.split(","):
                addr = part.strip()
                if addr:
                    resolved.append(addr)
        if resolved:
            return resolved

    # Fallback to global config
    recipients_raw = getattr(settings, "resend_recipients", "") or ""
    return [r.strip() for r in recipients_raw.split(",") if r.strip()]


def _has_pending_match_leads_tasks() -> bool:
    """Check whether any match_leads tasks are active or reserved.

    Uses Celery's control.inspect() to query all workers for tasks that are
    currently executing (active) or waiting to execute (reserved).  Returns
    ``True`` if any ``osint.match_leads`` tasks are found, ``False`` otherwise.

    If the broker or all workers are unreachable (inspect returns ``None``),
    we treat that as "no pending tasks" so the report is not blocked
    indefinitely by infrastructure outages.
    """
    inspector = celery_app.control.inspect(timeout=5.0)

    for task_map in (inspector.active(), inspector.reserved()):
        if task_map is None:
            continue
        for _worker, tasks in task_map.items():
            for task in tasks:
                if task.get("name") in (_MATCH_LEADS_TASK_NAME, _ANALYSIS_TASK_NAME):
                    return True

    return False


async def _generate_report_async(attempt: int = 0) -> dict[str, Any]:
    """Generate a prospecting report and send it via email.

    PDF generation and archival are separated from email delivery so that
    a Resend failure does not discard the already-archived PDF or undo
    the lead-status updates performed inside ``generate_report``.
    """
    from osint_core.metrics import (
        report_email_total,
        report_generation_duration_seconds,
        report_generation_total,
        report_leads_total,
    )
    from osint_core.services.plan_store import PlanStore
    from osint_core.services.prospecting_report import ProspectingReportGenerator
    from osint_core.services.resend_notifier import ResendNotifier

    start = time.monotonic()

    async with async_session() as db:
        generator = ProspectingReportGenerator()
        result = await generator.generate_report(db)

        if result is None:
            logger.info("prospecting_report_skipped: no new leads")
            report_generation_total.labels(outcome="skipped").inc()
            return {"status": "skipped", "reason": "no_new_leads"}

        # Load plan content for per-plan recipients
        store = PlanStore()
        plan_version = await store.get_active(db, _CAL_PLAN_ID)
        plan_content = plan_version.content if plan_version else None

    # --- PDF generated & archived, lead statuses updated at this point ---

    recipients = _resolve_recipients(plan_content)

    if not recipients:
        elapsed = time.monotonic() - start
        report_generation_duration_seconds.observe(elapsed)
        report_leads_total.labels(stage="rendered").set(result.lead_count)
        report_generation_total.labels(outcome="completed").inc()
        logger.warning(
            "prospecting_report_no_recipients: lead_count=%d",
            result.lead_count,
        )
        return {
            "status": "skipped",
            "reason": "no_recipients",
            "lead_count": result.lead_count,
        }

    # Attempt email delivery with retry — PDF is already archived, so only
    # the send is retried (not the full report generation).
    notifier = ResendNotifier()
    executive_summary = (
        f"Report generated with {result.lead_count} leads "
        f"on {result.report_date}."
    )

    sent = False
    email_start = time.monotonic()
    for email_attempt in range(1, _EMAIL_MAX_RETRIES + 1):
        try:
            sent = await notifier.send_report(
                pdf_bytes=result.pdf_bytes,
                executive_summary=executive_summary,
                recipients=recipients,
                report_date=result.report_date,
            )
        except Exception:
            logger.exception(
                "report_delivery_error: plan_id=%s "
                "email_attempt=%d/%d lead_count=%d artifact_uri=%s",
                _CAL_PLAN_ID,
                email_attempt,
                _EMAIL_MAX_RETRIES,
                result.lead_count,
                result.artifact_uri,
            )
            sent = False

        if sent:
            email_latency_ms = round((time.monotonic() - email_start) * 1000)
            logger.info(
                "report_email_delivered",
                artifact_uri=result.artifact_uri,
                recipient_count=len(recipients),
                latency_ms=email_latency_ms,
            )
            break

        if email_attempt < _EMAIL_MAX_RETRIES:
            backoff = _EMAIL_BACKOFF_BASE ** email_attempt
            logger.warning(
                "report_delivery_retry: plan_id=%s email_attempt=%d/%d "
                "backoff=%ds lead_count=%d artifact_uri=%s",
                _CAL_PLAN_ID,
                email_attempt,
                _EMAIL_MAX_RETRIES,
                backoff,
                result.lead_count,
                result.artifact_uri,
            )
            await asyncio.sleep(backoff)

    if not sent:
        logger.error(
            "report_email_exhausted: plan_id=%s email_attempts=%d "
            "lead_count=%d artifact_uri=%s recipients=%d task_attempt=%d",
            _CAL_PLAN_ID,
            _EMAIL_MAX_RETRIES,
            result.lead_count,
            result.artifact_uri,
            len(recipients),
            attempt,
        )

    # --- Emit Prometheus metrics ---
    elapsed = time.monotonic() - start
    report_generation_duration_seconds.observe(elapsed)
    report_leads_total.labels(stage="rendered").set(result.lead_count)
    report_email_total.labels(outcome="sent" if sent else "failed").inc()
    report_generation_total.labels(outcome="completed").inc()

    logger.info(
        "prospecting_report_complete: lead_count=%d artifact_uri=%s "
        "email_sent=%s recipients=%d elapsed=%.2fs task_attempt=%d",
        result.lead_count, result.artifact_uri, sent,
        len(recipients), elapsed, attempt,
    )

    return {
        "status": "completed",
        "lead_count": result.lead_count,
        "artifact_uri": result.artifact_uri,
        "email_sent": sent,
        "elapsed_seconds": round(elapsed, 2),
    }


class PipelineGuardResult:
    """Result of the pipeline completion guard check."""

    __slots__ = ("should_defer", "deferrals", "countdown")

    def __init__(self, *, should_defer: bool, deferrals: int, countdown: int = 0) -> None:
        self.should_defer = should_defer
        self.deferrals = deferrals
        self.countdown = countdown


def _check_pipeline_guard(headers: dict[str, Any] | None) -> PipelineGuardResult:
    """Evaluate whether report generation should be deferred.

    Reads the ``x_guard_deferrals`` counter from *headers* and checks whether
    any ``match_leads`` tasks are still running.  Returns a
    :class:`PipelineGuardResult` indicating whether to defer (and the
    recommended countdown) or proceed.
    """
    deferrals: int = (headers or {}).get("x_guard_deferrals", 0)

    if not _has_pending_match_leads_tasks():
        return PipelineGuardResult(should_defer=False, deferrals=deferrals)

    if deferrals >= _GUARD_MAX_DEFERRALS:
        logger.warning(
            "pipeline_guard_exhausted: proceeding despite pending "
            "match_leads tasks after %d deferrals",
            deferrals,
        )
        return PipelineGuardResult(should_defer=False, deferrals=deferrals)

    countdown = min(_GUARD_BACKOFF_BASE * (deferrals + 1), 600)
    logger.info(
        "pipeline_guard_deferred: pending match_leads tasks "
        "detected, deferring report generation "
        "deferral=%d/%d countdown=%ds",
        deferrals + 1,
        _GUARD_MAX_DEFERRALS,
        countdown,
    )
    return PipelineGuardResult(
        should_defer=True, deferrals=deferrals + 1, countdown=countdown,
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="osint.generate_prospecting_report",
    max_retries=3 + _GUARD_MAX_DEFERRALS,
)
def generate_prospecting_report_task(self: Any) -> dict[str, Any]:
    """Generate a prospecting report and email it via Resend.

    Scheduled via Celery beat at 8 AM and 3 PM America/Chicago time.
    Gracefully skips if no new leads exist or no recipients are configured.

    Before generating, checks for in-progress match_leads tasks and defers
    (up to ``_GUARD_MAX_DEFERRALS`` times) to avoid reporting on incomplete
    pipeline data.  After the guard passes, retries up to 3 more times with
    exponential backoff for genuine failures.
    """
    # --- Pipeline completion guard ---
    guard = _check_pipeline_guard(self.request.headers)

    if guard.should_defer:
        raise self.retry(
            countdown=guard.countdown,
            headers={"x_guard_deferrals": guard.deferrals},
        )

    # --- Report generation ---
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _generate_report_async(attempt=self.request.retries),
        )
    except Exception as exc:
        logger.exception("Prospecting report generation failed")
        # Only count as a final failure when all retries are exhausted
        retries_used = self.request.retries - guard.deferrals
        if retries_used >= 3:  # max_retries for generation (excluding guard deferrals)
            from osint_core.metrics import report_generation_total

            report_generation_total.labels(outcome="failed").inc()
        raise self.retry(
            exc=exc,
            countdown=min(2 ** self.request.retries * 60, 300),
            headers={"x_guard_deferrals": guard.deferrals},
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
