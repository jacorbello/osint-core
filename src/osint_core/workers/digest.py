"""Celery digest task — compile accumulated events into periodic digest reports."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Default digest window in hours for each period label.
_PERIOD_HOURS: dict[str, int] = {
    "daily": 24,
    "weekly": 168,  # 7 * 24
    "shift": 8,
}

# Severity levels in descending priority order.
_SEVERITIES = ("critical", "high", "medium", "low", "info")


def _window_hours(period: str, hours: int | None) -> int:
    """Resolve the time-window length in hours.

    Args:
        period: Named period (``"daily"``, ``"weekly"``, ``"shift"``).
        hours: Explicit override when not ``None``.

    Returns:
        Window length in hours.
    """
    if hours is not None and hours > 0:
        return hours
    return _PERIOD_HOURS.get(period, 24)


def _build_severity_breakdown(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count events per severity level.

    Args:
        events: List of event dicts, each with an optional ``severity`` key.

    Returns:
        Mapping of severity label → count (only non-zero severities included).
    """
    breakdown: dict[str, int] = {}
    for evt in events:
        sev = (evt.get("severity") or "info").lower()
        breakdown[sev] = breakdown.get(sev, 0) + 1
    return {k: v for k, v in breakdown.items() if v}


def _build_source_breakdown(events: list[dict[str, Any]]) -> dict[str, int]:
    """Count events per source.

    Args:
        events: List of event dicts, each with an optional ``source_id`` key.

    Returns:
        Mapping of source_id → count (only non-zero sources included).
    """
    breakdown: dict[str, int] = {}
    for evt in events:
        src = evt.get("source_id") or "unknown"
        breakdown[src] = breakdown.get(src, 0) + 1
    return {k: v for k, v in breakdown.items() if v}


@celery_app.task(bind=True, name="osint.compile_digest", max_retries=3)  # type: ignore[untyped-decorator]
def compile_digest(
    self: Any,
    plan_id: str,
    period: str = "daily",
    hours: int | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    """Compile a digest of recent events for a plan.

    Aggregates events from the past ``hours`` (or the window implied by
    ``period``) and groups them by severity and source.  The resulting
    digest record is persisted to the database and optionally dispatched
    via ``send_notification``.

    This task is typically scheduled via Celery Beat (configured through
    the plan engine's beat schedule builder).

    Pipeline steps:
      1. Compute the time window: ``[now - window_hours, now]``.
      2. Query the database for events linked to ``plan_id`` within the
         window (filtered to those not already included in a digest).
      3. Group events by severity and source_id.
      4. Persist a ``Brief`` record (digest) with the summary.
      5. Optionally chain ``send_notification`` with the digest brief ID.

    Args:
        plan_id: The plan whose events should be digested.
        period: Named window — ``"daily"`` (24h), ``"weekly"`` (7d), or
            ``"shift"`` (8h).  Ignored when ``hours`` is provided explicitly.
        hours: Explicit window length in hours.  Overrides ``period`` when set.
        notify: When ``True``, chain ``send_notification`` after persisting.

    Returns:
        A dict with:
        - ``plan_id``: the input plan ID.
        - ``period``: effective period label.
        - ``window_hours``: resolved window in hours.
        - ``window_start`` / ``window_end``: ISO-8601 timestamps.
        - ``status``: ``"ok"`` or ``"empty"`` when no events were found.
        - ``alert_count``: total events included in the digest.
        - ``severity_breakdown``: mapping of severity → count.
        - ``source_breakdown``: mapping of source_id → count.
        - ``digest_id``: ID of the persisted digest record (stub: ``None``).
    """
    logger.info("Compiling %s digest for plan: %s", period, plan_id)

    window_hours = _window_hours(period, hours)
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=window_hours)

    logger.info(
        "digest_window plan_id=%s window_start=%s window_end=%s hours=%d",
        plan_id,
        window_start.isoformat(),
        now.isoformat(),
        window_hours,
    )

    # --- Load events (DB stub) ---
    # In production:
    #   async with async_session() as db:
    #       result = await db.execute(
    #           select(Event)
    #           .join(PlanVersion, Event.plan_version_id == PlanVersion.id)
    #           .where(PlanVersion.plan_id == plan_id)
    #           .where(Event.ingested_at >= window_start)
    #           .where(Event.ingested_at <= now)
    #           .where(Event.metadata_["digested"].as_boolean() != True)
    #       )
    #       events_orm = result.scalars().all()
    #       events = [
    #           {
    #               "event_id": str(e.id),
    #               "title": e.title,
    #               "severity": e.severity,
    #               "source_id": e.source_id,
    #               "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
    #           }
    #           for e in events_orm
    #       ]
    events: list[dict[str, Any]] = []

    if not events:
        logger.info("digest_empty plan_id=%s period=%s", plan_id, period)
        return {
            "plan_id": plan_id,
            "period": period,
            "window_hours": window_hours,
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
            "status": "empty",
            "alert_count": 0,
            "severity_breakdown": {},
            "source_breakdown": {},
            "digest_id": None,
        }

    severity_breakdown = _build_severity_breakdown(events)
    source_breakdown = _build_source_breakdown(events)

    # --- Persist digest (DB stub) ---
    # In production:
    #   severity_lines = ", ".join(
    #       f"{count} {sev}" for sev, count in sorted(
    #           severity_breakdown.items(),
    #           key=lambda kv: _SEVERITIES.index(kv[0]) if kv[0] in _SEVERITIES else 99,
    #       )
    #   )
    #   content_md = (
    #       f"# OSINT Digest — {period.title()} ({now.strftime('%Y-%m-%d %H:%M UTC')})\n\n"
    #       f"**Plan:** {plan_id}  \n"
    #       f"**Window:** {window_start.strftime('%Y-%m-%d %H:%M')} – "
    #       f"{now.strftime('%Y-%m-%d %H:%M')} UTC\n\n"
    #       f"**Total events:** {len(events)}  \n"
    #       f"**Severity breakdown:** {severity_lines}\n"
    #   )
    #   digest_record = Brief(
    #       title=f"Digest: {plan_id} ({period})",
    #       content_md=content_md,
    #       event_ids=[uuid.UUID(e["event_id"]) for e in events],
    #       generated_by="digest",
    #   )
    #   db.add(digest_record)
    #   # Mark events as digested
    #   for e in events_orm:
    #       e.metadata_["digested"] = True
    #   await db.commit()
    #   await db.refresh(digest_record)
    #   digest_id = str(digest_record.id)
    digest_id: str | None = None

    logger.info(
        "digest_compiled plan_id=%s period=%s alert_count=%d severity=%s",
        plan_id,
        period,
        len(events),
        severity_breakdown,
    )

    result: dict[str, Any] = {
        "plan_id": plan_id,
        "period": period,
        "window_hours": window_hours,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "status": "ok",
        "alert_count": len(events),
        "severity_breakdown": severity_breakdown,
        "source_breakdown": source_breakdown,
        "digest_id": digest_id,
    }

    # --- Optionally notify (stub) ---
    # In production (when digest_id is available):
    #   if notify and digest_id:
    #       from osint_core.workers.notify import send_notification
    #       send_notification.delay(digest_id)
    if notify:
        logger.info("digest_notify_skipped_no_digest_id plan_id=%s", plan_id)

    return result
