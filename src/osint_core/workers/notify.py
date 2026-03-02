"""Celery notification task — dispatch alert notifications via configured channels."""

from __future__ import annotations

import logging

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.send_notification", max_retries=3)
def send_notification(self, alert_id: str) -> dict:
    """Send notifications for an alert through all matched routes.

    Pipeline steps:
      1. Load the alert from the database by alert_id
      2. Load notification routes from the plan config
      3. Match routes by alert severity
      4. For each matched route:
         a. Format the notification message
         b. Dispatch to each channel (Gotify, Apprise, etc.)
      5. Record delivery status

    Returns a summary dict with dispatch results.

    Note: Full integration with Apprise/Gotify is deferred until the
    notification backends are configured.  This task currently serves as
    the registered entry point for the notification pipeline.
    """
    logger.info("Dispatching notification for alert: %s", alert_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Load the alert by ID from the DB
    # 2. Load NotificationRoutes from the plan/config
    # 3. Create a NotificationService with those routes
    # 4. Call match_routes(alert.severity)
    # 5. For each matched route, format the message and dispatch
    #    - Gotify: POST to gotify server with priority
    #    - Apprise: Use apprise library for multi-channel dispatch
    # 6. Record delivery status per channel

    return {
        "alert_id": alert_id,
        "status": "stub",
        "dispatched_to": [],
    }
