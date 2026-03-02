"""Tests for notification dispatch — route matching and message formatting."""

from osint_core.services.notification import NotificationRoute, NotificationService


def test_route_matching():
    route = NotificationRoute(
        name="critical",
        severity_gte="high",
        channels=[{"type": "gotify", "application": "test", "priority": 8}],
    )
    svc = NotificationService(routes=[route])
    matched = svc.match_routes(severity="critical")
    assert len(matched) == 1
    assert matched[0].name == "critical"


def test_no_route_for_low_severity():
    route = NotificationRoute(
        name="critical",
        severity_gte="high",
        channels=[{"type": "gotify", "application": "test", "priority": 8}],
    )
    svc = NotificationService(routes=[route])
    matched = svc.match_routes(severity="info")
    assert len(matched) == 0


def test_route_matching_exact_severity():
    """A route with severity_gte='medium' should match severity='medium'."""
    route = NotificationRoute(
        name="medium-alerts",
        severity_gte="medium",
        channels=[{"type": "gotify", "application": "test", "priority": 5}],
    )
    svc = NotificationService(routes=[route])
    matched = svc.match_routes(severity="medium")
    assert len(matched) == 1


def test_multiple_routes_matched():
    """Multiple routes can match the same severity."""
    route_high = NotificationRoute(
        name="high-slack",
        severity_gte="high",
        channels=[{"type": "apprise", "url": "slack://token"}],
    )
    route_medium = NotificationRoute(
        name="medium-email",
        severity_gte="medium",
        channels=[{"type": "apprise", "url": "mailto://user@example.com"}],
    )
    svc = NotificationService(routes=[route_high, route_medium])
    matched = svc.match_routes(severity="high")
    assert len(matched) == 2


def test_multiple_routes_partial_match():
    """Only routes whose severity_gte is met should be returned."""
    route_critical = NotificationRoute(
        name="critical-only",
        severity_gte="critical",
        channels=[{"type": "gotify", "application": "test", "priority": 10}],
    )
    route_low = NotificationRoute(
        name="all-alerts",
        severity_gte="low",
        channels=[{"type": "apprise", "url": "json://endpoint"}],
    )
    svc = NotificationService(routes=[route_critical, route_low])
    matched = svc.match_routes(severity="high")
    assert len(matched) == 1
    assert matched[0].name == "all-alerts"


def test_format_alert_message():
    """Format an alert into a structured notification message."""
    svc = NotificationService(routes=[])
    msg = svc.format_message(
        title="CVE-2026-0001 detected",
        summary="A critical vulnerability was found in target system.",
        severity="critical",
        indicators=["CVE-2026-0001", "192.168.1.100"],
    )
    assert "CVE-2026-0001 detected" in msg["title"]
    assert "critical" in msg["body"].lower()
    assert "CVE-2026-0001" in msg["body"]
    assert "192.168.1.100" in msg["body"]


def test_format_alert_message_no_indicators():
    """Format should work even with an empty indicator list."""
    svc = NotificationService(routes=[])
    msg = svc.format_message(
        title="General alert",
        summary="Something happened.",
        severity="low",
        indicators=[],
    )
    assert "General alert" in msg["title"]
    assert "low" in msg["body"].lower()


def test_no_routes_returns_empty():
    """A service with no routes should match nothing."""
    svc = NotificationService(routes=[])
    assert svc.match_routes(severity="critical") == []


def test_route_info_severity_matches_all():
    """A route with severity_gte='info' should match everything."""
    route = NotificationRoute(
        name="catch-all",
        severity_gte="info",
        channels=[{"type": "apprise", "url": "json://log"}],
    )
    svc = NotificationService(routes=[route])
    for sev in ("info", "low", "medium", "high", "critical"):
        matched = svc.match_routes(severity=sev)
        assert len(matched) == 1, f"Expected match for severity={sev}"
