"""Celery notification task — dispatch alert notifications via Gotify."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from osint_core.services.notification import SEVERITY_ORDER, NotificationRoute, NotificationService
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


@celery_app.task(bind=True, name="osint.send_notification", max_retries=3)  # type: ignore[untyped-decorator]
def send_notification(self: Any, event_id: str, event_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a Gotify push notification for a scored event.

    Args:
        event_id: The ID of the event to notify about.
        event_data: Optional pre-loaded event dict from ``score_event``.
            Expected keys: ``severity``, ``title``, ``summary``,
            ``source_id``, ``event_type``, ``indicators`` (list[str]).
            If omitted, the task checks severity from a minimal fallback
            and skips dispatch (DB integration deferred).

    Returns:
        A dict with keys:
            - ``event_id``: The input event ID.
            - ``notified``: Whether a notification was dispatched.
            - ``reason``: Human-readable explanation.
    """
    logger.info("send_notification called for event: %s", event_id)

    data = event_data or {}
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
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

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
