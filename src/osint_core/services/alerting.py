"""Alerting service — alert creation, fingerprint dedup, and quiet hours.

Provides deterministic fingerprinting for deduplication, threshold-based
alerting decisions, quiet-hours checking, and severity escalation logic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import time

# Severity ordering for comparisons: info=0, low=1, medium=2, high=3, critical=4
SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def compute_fingerprint(
    plan_id: str,
    indicators: list[str],
    canonical_url: str,
) -> str:
    """Compute a deterministic SHA-256 fingerprint for alert deduplication.

    The fingerprint is derived from the plan ID, a sorted list of indicators,
    and the canonical URL.  Sorting the indicators ensures that order does not
    affect the result.

    Args:
        plan_id: The plan that generated this alert.
        indicators: List of indicator values (e.g. CVE IDs, hashes).
        canonical_url: The canonical URL of the source item.

    Returns:
        A 64-character lowercase hex SHA-256 digest.
    """
    payload = json.dumps(
        {
            "plan_id": plan_id,
            "indicators": sorted(indicators),
            "url": canonical_url,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def should_alert(
    score: float,
    severity: str,
    threshold: float,
) -> bool:
    """Decide whether an event should generate an alert.

    An alert is produced when:
      - The score meets or exceeds the threshold, OR
      - The severity is ``critical`` (always alerts regardless of threshold).

    Args:
        score: Numeric relevance score of the event.
        severity: Severity label (info, low, medium, high, critical).
        threshold: Minimum score required to trigger an alert.

    Returns:
        True if the event should generate an alert.
    """
    if severity == "critical":
        return True
    return score >= threshold


def check_quiet_hours(
    current_time: time,
    quiet_start: time | None,
    quiet_end: time | None,
) -> bool:
    """Check whether the current time falls within the quiet-hours window.

    Quiet hours suppress non-critical notifications.  The window may span
    midnight (e.g. 22:00 - 06:00).

    Args:
        current_time: The time to check.
        quiet_start: Start of the quiet-hours window, or None to disable.
        quiet_end: End of the quiet-hours window, or None to disable.

    Returns:
        True if currently in quiet hours; False otherwise.
    """
    if quiet_start is None or quiet_end is None:
        return False

    # Window does not span midnight (e.g. 12:00 - 14:00)
    if quiet_start <= quiet_end:
        return quiet_start <= current_time <= quiet_end

    # Window spans midnight (e.g. 22:00 - 06:00)
    return current_time >= quiet_start or current_time <= quiet_end


def should_escalate(
    current_severity: str,
    previous_severity: str,
    corroborating_sources: int,
) -> bool:
    """Decide whether an alert should be escalated.

    Escalation occurs when:
      - The severity has increased compared to the previous alert, OR
      - Three or more independent corroborating sources confirm the alert.

    Args:
        current_severity: Current alert severity label.
        previous_severity: Previous alert severity label.
        corroborating_sources: Number of independent sources confirming the alert.

    Returns:
        True if the alert should be escalated.
    """
    current_level = SEVERITY_ORDER.get(current_severity, 0)
    previous_level = SEVERITY_ORDER.get(previous_severity, 0)

    if current_level > previous_level:
        return True

    if corroborating_sources >= 3:
        return True

    return False
