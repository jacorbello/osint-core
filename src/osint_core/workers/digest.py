"""Celery digest task — compile accumulated alerts into periodic digest reports."""

from __future__ import annotations

import logging

from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="osint.compile_digest", max_retries=3)
def compile_digest(self, plan_id: str, period: str = "daily") -> dict:
    """Compile accumulated alerts into a digest notification.

    This task is typically scheduled via Celery Beat to run at the end of
    quiet hours, collecting all alerts that were suppressed during the
    quiet-hours window and compiling them into a single digest message.

    Pipeline steps:
      1. Load alerts for the plan within the digest period
      2. Group alerts by severity and source
      3. Generate a summary with counts, top indicators, and severity breakdown
      4. Format digest as a structured notification message
      5. Dispatch via NotificationService to digest-configured channels
      6. Mark included alerts as digested

    Args:
        plan_id: The plan to compile the digest for.
        period: Digest period — 'daily', 'weekly', or 'shift' (default: 'daily').

    Returns:
        A summary dict with digest compilation results.

    Note: Full DB integration is deferred until the database layer is
    connected.  This task currently serves as the registered entry point
    for the digest pipeline.
    """
    logger.info("Compiling %s digest for plan: %s", period, plan_id)

    # --- Stub implementation ---
    # In production this would:
    # 1. Query alerts table for plan_id within the period window
    #    (e.g. last 24h for daily, last 7d for weekly)
    # 2. Filter to alerts not yet included in a digest
    # 3. Group by severity: {critical: [...], high: [...], ...}
    # 4. Extract top indicators across all alerts
    # 5. Build a digest summary:
    #    - Total alert count
    #    - Severity breakdown (N critical, M high, etc.)
    #    - Top indicators by frequency
    #    - Notable escalations
    # 6. Format via NotificationService.format_message()
    # 7. Dispatch to digest-specific notification routes
    # 8. Mark alerts as digested (set digest_id foreign key)

    return {
        "plan_id": plan_id,
        "period": period,
        "status": "stub",
        "alert_count": 0,
        "severity_breakdown": {},
    }
