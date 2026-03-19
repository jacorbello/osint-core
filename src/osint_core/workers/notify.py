"""Celery notification task — dispatch alert notifications via configured channels."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
import jinja2
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

# Slack severity → sidebar color (hex).
_SEVERITY_TO_COLOR: dict[str, str] = {
    "info": "#36a64f",      # green
    "low": "#2196f3",       # blue
    "medium": "#ff9800",    # amber
    "high": "#ff5722",      # orange-red
    "critical": "#d32f2f",  # red
}

# Key fields that should be present for a complete notification.
_REQUIRED_FIELDS = {"title", "summary", "severity", "source_id"}

# Jinja2 environment for rendering webhook payload templates.
_JINJA_ENV = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=False,
)

# Default webhook payload template used when none is provided in the channel config.
_DEFAULT_WEBHOOK_TEMPLATE = """{
  "title": {{ title | tojson }},
  "severity": {{ severity | tojson }},
  "summary": {{ summary | tojson }},
  "source_id": {{ source_id | tojson }},
  "event_type": {{ event_type | tojson }},
  "indicators": {{ indicators | tojson }}
}"""


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


def _render_webhook_payload(template_str: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 payload template with the given event context.

    Args:
        template_str: Jinja2 template string for the webhook body.
        context: Dict of event fields available to the template.

    Returns:
        The rendered string payload.
    """
    template = _JINJA_ENV.from_string(template_str)
    return template.render(**context)


def _post_to_webhook(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    payload: str,
) -> bool:
    """Send an HTTP request to a webhook URL.

    Args:
        url: The webhook endpoint URL.
        method: HTTP method (default ``POST``).
        headers: Optional dict of HTTP headers.
        payload: The rendered string payload (typically JSON).

    Returns:
        True on success (2xx response).

    Raises:
        httpx.HTTPStatusError: On 4xx/5xx responses (5xx triggers Celery retry).
        httpx.RequestError: On connection failures.
    """
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    try:
        resp = httpx.request(
            method.upper(),
            url,
            headers=req_headers,
            content=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Webhook returned HTTP %s: %s", exc.response.status_code, exc)
        raise
    except httpx.RequestError as exc:
        logger.error("Webhook request failed: %s", exc)
        raise


def _build_slack_blocks(
    title: str,
    summary: str,
    severity: str,
    indicators: list[str],
) -> dict[str, Any]:
    """Build a Slack incoming-webhook payload with Block Kit attachments.

    Returns a dict ready for ``json=`` in an httpx POST to a Slack webhook URL.
    The payload uses *attachments* (not top-level blocks) so that the severity
    colour sidebar is rendered.
    """
    color = _SEVERITY_TO_COLOR.get(severity, _SEVERITY_TO_COLOR["info"])

    fields: list[dict[str, Any]] = [
        {"type": "mrkdwn", "text": f"*Severity:*\n{severity.upper()}"},
    ]

    if indicators:
        indicator_text = ", ".join(indicators[:10])
        if len(indicators) > 10:
            indicator_text += f" (+{len(indicators) - 10} more)"
        fields.append({"type": "mrkdwn", "text": f"*Indicators:*\n{indicator_text}"})

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\n{summary}"},
        },
        {
            "type": "section",
            "fields": fields,
        },
    ]

    return {
        "attachments": [
            {
                "color": color,
                "blocks": blocks,
            }
        ],
    }


def _post_to_slack(
    webhook_url: str,
    title: str,
    summary: str,
    severity: str,
    indicators: list[str],
) -> bool:
    """POST a notification to a Slack incoming webhook.

    Args:
        webhook_url: The Slack incoming webhook URL.
        title: Alert title.
        summary: Alert summary text.
        severity: Severity label (used for colour mapping).
        indicators: List of indicator values.

    Returns True on success, False on failure (non-HTTP errors are raised).
    """
    if not webhook_url:
        logger.warning("Slack webhook URL is empty; skipping Slack dispatch")
        return False

    payload = _build_slack_blocks(title, summary, severity, indicators)
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Slack returned HTTP %s: %s", exc.response.status_code, exc)
        raise
    except httpx.RequestError as exc:
        logger.error("Slack request failed: %s", exc)
        raise


def _dispatch_channel(
    channel: dict[str, Any],
    *,
    msg: dict[str, str],
    event_data: dict[str, Any],
    priority: int,
) -> bool:
    """Dispatch a notification to a single channel.

    Args:
        channel: Channel configuration dict with at minimum a ``type`` key.
        msg: Formatted message dict with ``title`` and ``body``.
        event_data: Full event data dict for webhook template rendering.
        priority: Gotify priority level.

    Returns:
        True if the notification was dispatched successfully.

    Raises:
        httpx.HTTPStatusError: On HTTP error responses (retryable).
        httpx.RequestError: On connection errors (retryable).
        ValueError: If the channel type is unknown.
    """
    channel_type = channel.get("type", "").lower()

    if channel_type == "gotify":
        return _post_to_gotify(msg["title"], msg["body"], priority)

    if channel_type == "webhook":
        url = channel.get("url")
        if not url:
            logger.warning("Webhook channel missing 'url'; skipping")
            return False

        method = channel.get("method", "POST")
        headers = channel.get("headers") or {}
        template_str = channel.get("payload_template") or _DEFAULT_WEBHOOK_TEMPLATE

        payload = _render_webhook_payload(template_str, event_data)
        return _post_to_webhook(url, method=method, headers=headers, payload=payload)

    if channel_type == "slack":
        webhook_url = channel.get("webhook_url", "")
        return _post_to_slack(
            webhook_url,
            event_data.get("title", ""),
            event_data.get("summary", ""),
            event_data.get("severity", "info"),
            event_data.get("indicators", []),
        )

    raise ValueError(f"Unknown notification channel type: {channel_type!r}")



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
    self: Any,
    event_id: str,
    event_data: dict[str, Any] | None = None,
    channels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Send notifications for a scored event via configured channels.

    When *channels* is ``None`` (legacy callers), the task falls back to
    dispatching via Gotify and Slack using env-var configuration.

    Args:
        event_id: The ID of the event to notify about.
        event_data: Optional pre-loaded event dict from ``score_event``.
            Expected keys: ``severity``, ``title``, ``summary``,
            ``source_id``, ``event_type``, ``indicators`` (list[str]).
            When omitted or incomplete, the task fetches the full event
            from the database and supplements missing fields.
        channels: Optional list of channel config dicts from plan YAML.
            Each dict must have a ``type`` key (``"gotify"`` or ``"webhook"``).
            Webhook channels support ``url``, ``method``, ``headers``, and
            ``payload_template`` (Jinja2).

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

    # Template context available to Jinja2 webhook payloads.
    template_context: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "severity": severity,
        "source_id": source_id,
        "event_type": event_type,
        "indicators": indicators,
        "event_id": event_id,
        "priority": priority,
    }

    # Resolve channel list: use provided channels, or fall back to
    # Gotify + Slack (env-var based) for backward compatibility.
    effective_channels: list[dict[str, Any]]
    if channels is not None:
        effective_channels = channels
    else:
        effective_channels = [{"type": "gotify"}]
        slack_url = os.environ.get("OSINT_SLACK_WEBHOOK_URL", "")
        if slack_url:
            effective_channels.append({"type": "slack", "webhook_url": slack_url})

    dispatched_any = False
    retryable_errors: list[Exception] = []
    errors: list[str] = []

    for ch in effective_channels:
        try:
            ok = _dispatch_channel(
                ch, msg=msg, event_data=template_context, priority=priority,
            )
            if ok:
                dispatched_any = True
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "Channel %s dispatch failed for event %s: %s",
                ch.get("type"), event_id, exc,
            )
            retryable_errors.append(exc)
            errors.append(f"{ch.get('type')}: {exc}")
        except ValueError as exc:
            errors.append(str(exc))

    # Only retry if ALL channels failed — partial success is still success.
    if retryable_errors and not dispatched_any:
        raise self.retry(
            exc=retryable_errors[0],
            countdown=2 ** self.request.retries,
        )

    if not dispatched_any and not errors:
        return {
            "event_id": event_id,
            "notified": False,
            "reason": "no notification channels configured",
        }

    if not dispatched_any:
        return {
            "event_id": event_id,
            "notified": False,
            "reason": f"All channels failed: {'; '.join(errors)}",
        }

    logger.info("Notification dispatched for event %s (severity=%s)", event_id, severity)
    return {
        "event_id": event_id,
        "notified": True,
        "reason": f"severity '{severity}' met threshold '{threshold}'",
    }
