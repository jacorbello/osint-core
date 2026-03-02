"""Notification service — route matching, message formatting, and dispatch.

Supports routing alerts to different channels (Gotify, Apprise) based on
severity thresholds, and formatting alert data into structured messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Severity ordering for comparisons: info=0, low=1, medium=2, high=3, critical=4
SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


@dataclass
class NotificationRoute:
    """A notification routing rule.

    Attributes:
        name: Human-readable name for this route.
        severity_gte: Minimum severity that triggers this route.
            Routes match when the alert severity is greater than or equal
            to this value in the severity ordering.
        channels: List of channel configurations (dicts with at minimum
            a ``type`` key, e.g. ``{"type": "gotify", "priority": 8}``).
    """

    name: str
    severity_gte: str
    channels: list[dict] = field(default_factory=list)


class NotificationService:
    """Dispatch notifications to matched routes based on severity.

    Args:
        routes: List of :class:`NotificationRoute` instances to evaluate.
    """

    def __init__(self, routes: list[NotificationRoute]) -> None:
        self._routes = routes

    def match_routes(self, severity: str) -> list[NotificationRoute]:
        """Return all routes whose severity threshold is met.

        A route matches when the given severity is >= the route's
        ``severity_gte`` value according to :data:`SEVERITY_ORDER`.

        Args:
            severity: The alert severity label to match against.

        Returns:
            List of matching :class:`NotificationRoute` instances.
        """
        alert_level = SEVERITY_ORDER.get(severity, 0)
        matched: list[NotificationRoute] = []
        for route in self._routes:
            route_level = SEVERITY_ORDER.get(route.severity_gte, 0)
            if alert_level >= route_level:
                matched.append(route)
        return matched

    def format_message(
        self,
        title: str,
        summary: str,
        severity: str,
        indicators: list[str],
    ) -> dict[str, str]:
        """Format an alert into a notification message payload.

        Args:
            title: Alert title / headline.
            summary: Brief description of the alert.
            severity: Severity label.
            indicators: List of indicator values (CVEs, IPs, hashes, etc.).

        Returns:
            A dict with ``title`` and ``body`` keys suitable for dispatch.
        """
        indicator_section = ""
        if indicators:
            bullet_list = "\n".join(f"  - {ind}" for ind in indicators)
            indicator_section = f"\nIndicators:\n{bullet_list}"

        body = (
            f"Severity: {severity.upper()}\n"
            f"\n"
            f"{summary}"
            f"{indicator_section}"
        )

        return {
            "title": title,
            "body": body,
        }
