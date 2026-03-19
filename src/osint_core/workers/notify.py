"""Celery notification task — dispatch alert notifications via Gotify."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from osint_core.config import settings
from osint_core.models.event import Event
from osint_core.services.notification import SEVERITY_ORDER, NotificationService
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Severity threshold for notifications — overridable via env var.
# Defaults to "medium" if not set.
_DEFAULT_THRESHOLD = "medium"

SEVERITY_LABELS = ("info", "low", "medium", "high", "critical")

# Priority mappings from severity to Gotify priority (1-10).
_SEVERITY_TO_PRIORITY: dict[str, int] = {
    "info": 1,
    "low": 3,
    "medium": 5,
    "high": 8,
    "critical": 10,
}

# Key fields that should be present for a complete notification.
_REQUIRED_FIELDS = {"title", "summary", "severity", "source_id"}


def _gotify_url() -> str:
    return os.environ.get("OSINT_GOTIFY_URL", "http://gotify/message")


def _gotify_token() -> str:
    return os.environ.get("OSINT_GOTIFY_TOKEN", "")


def _notify_threshold() -> str:
    raw = os.environ.get("OSINT_NOTIFY_THRESHOLD", _DEFAULT_THRESHOLD).lower()
    return raw if raw in SEVERITY_ORDER else _DEFAULT_THRESHOLD


def _post_to_gotify(title: str, message: str, priority: int) -> bool:
    """POST a notification to the Gotify API.

    Returns True on success, False on failure.
    """
    token = _gotify_token()
    if not token:
        logger.warning("OSINT_GOTIFY_TOKEN is not set; skipping Gotify dispatch")
        return False

    url = _gotify_url()
    try:
        resp = httpx.post(
            url,
            headers={"X-Gotify-Key": token},
            json={"title": title, "message": message, "priority": priority},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Gotify returned HTTP %s: %s", exc.response.status_code, exc)
        raise
    except httpx.RequestError as exc:
        logger.error("Gotify request failed: %s", exc)
        raise


def _needs_db_fetch(event_data: dict[str, Any] | None) -> bool:
    """Return True if event_data is missing or lacks required fields."""
    if event_data is None:
        return True
    return not _REQUIRED_FIELDS.issubset(
        {k for k, v in event_data.items() if v is not None}
    )


async def _fetch_event_data(event_id: str) -> dict[str, Any] | None:
    """Fetch event data from the database by *event_id*.

    Returns a dict with event fields, or ``None`` if the event is not found
    or the fetch fails.
    """
    try:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with session_factory() as db:
                event = await db.get(Event, event_id)
                if event is None:
                    logger.warning("Event %s not found in DB", event_id)
                    return None

                # Extract indicator values from the relationship.
                indicator_values: list[str] = []
                if event.indicators:
                    indicator_values = [ind.value for ind in event.indicators]

                return {
                    "title": event.title,
                    "summary": event.summary or event.nlp_summary,
                    "severity": event.severity,
                    "source_id": event.source_id,
                    "event_type": event.event_type,
                    "indicators": indicator_values,
                }
        finally:
            await engine.dispose()
    except Exception:
        logger.exception("Failed to fetch event %s from DB", event_id)
        return None


@celery_app.task(bind=True, name="osint.send_notification", max_retries=3)  # type: ignore[untyped-decorator]
def send_notification(
    self: Any, event_id: str, event_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Send a Gotify push notification for a scored event.

    Args:
        event_id: The ID of the event to notify about.
        event_data: Optional pre-loaded event dict from ``score_event``.
            Expected keys: ``severity``, ``title``, ``summary``,
            ``source_id``, ``event_type``, ``indicators`` (list[str]).
            When omitted or incomplete, the task fetches the full event
            from the database and supplements missing fields.

    Returns:
        A dict with keys:
            - ``event_id``: The input event ID.
            - ``notified``: Whether a notification was dispatched.
            - ``reason``: Human-readable explanation.
    """
    logger.info("send_notification called for event: %s", event_id)

    # --- DB fallback: fetch missing data when event_data is absent/incomplete ---
    data: dict[str, Any] = dict(event_data) if event_data else {}

    if _needs_db_fetch(event_data):
        logger.info("Event data incomplete for %s; fetching from DB", event_id)
        loop = asyncio.new_event_loop()
        try:
            db_data = loop.run_until_complete(_fetch_event_data(event_id))
        finally:
            loop.close()

        if db_data:
            # Supplement: only fill keys that are missing or None in caller data.
            for key, value in db_data.items():
                if data.get(key) is None and value is not None:
                    data[key] = value

    severity: str = data.get("severity") or "info"
    threshold: str = _notify_threshold()

    threshold_level = SEVERITY_ORDER.get(threshold, 0)
    event_level = SEVERITY_ORDER.get(severity, 0)

    if event_level < threshold_level:
        logger.info(
            "Event %s severity=%s is below threshold=%s; skipping",
            event_id, severity, threshold,
        )
        return {
            "event_id": event_id,
            "notified": False,
            "reason": f"severity '{severity}' below threshold '{threshold}'",
        }

    # Build notification content from event data.
    source_id: str = data.get("source_id", "unknown-source")
    event_type: str = data.get("event_type", "event")
    title: str = data.get("title") or f"[{severity.upper()}] {source_id} — {event_type}"
    summary: str = data.get("summary") or "No summary available."
    indicators: list[str] = data.get("indicators") or []

    svc = NotificationService(routes=[])
    msg = svc.format_message(
        title=title,
        summary=summary,
        severity=severity,
        indicators=indicators,
    )

    priority = _SEVERITY_TO_PRIORITY.get(severity, 5)

    try:
        dispatched = _post_to_gotify(msg["title"], msg["body"], priority)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Gotify dispatch failed for event %s; retrying. %s", event_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc

    if not dispatched:
        return {
            "event_id": event_id,
            "notified": False,
            "reason": "Gotify token not configured",
        }

    logger.info("Notification dispatched for event %s (severity=%s)", event_id, severity)
    return {
        "event_id": event_id,
        "notified": True,
        "reason": f"severity '{severity}' met threshold '{threshold}'",
    }
