"""Tests for the Celery notification worker task."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from osint_core.workers.notify import send_notification


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_send_notification_task_registered():
    """The send_notification task should be registered with the correct name."""
    assert send_notification.name == "osint.send_notification"


def test_send_notification_task_max_retries():
    """The send_notification task should have max_retries=3."""
    assert send_notification.max_retries == 3


def test_send_notification_is_bound():
    """The send_notification task should be a bound task (bind=True)."""
    assert send_notification.__bound__ is True


# ---------------------------------------------------------------------------
# Threshold / skip logic
# ---------------------------------------------------------------------------


def test_below_threshold_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events below the configured threshold should not trigger a notification."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "high")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "test-token")

    result = send_notification.run(
        "evt-001",
        {"severity": "low", "title": "Minor event", "summary": "Nothing to see here."},
    )

    assert result["notified"] is False
    assert "below threshold" in result["reason"]
    assert result["event_id"] == "evt-001"


def test_above_threshold_sends_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events at or above the threshold should send a Gotify notification."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "test-token")
    monkeypatch.setenv("OSINT_GOTIFY_URL", "http://gotify-test/message")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_post:
        result = send_notification.run(
            "evt-002",
            {
                "severity": "high",
                "title": "CVE-2026-9999 critical",
                "summary": "A critical vulnerability was found.",
                "source_id": "nvd",
                "event_type": "cve",
                "indicators": ["CVE-2026-9999", "192.168.1.1"],
            },
        )

    assert result["notified"] is True
    assert result["event_id"] == "evt-002"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    # Priority should be 8 for "high"
    assert call_kwargs.args[2] == 8


def test_exact_threshold_severity_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """An event exactly at the threshold should be dispatched."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True) as mock_post:
        result = send_notification.run(
            "evt-003",
            {"severity": "medium", "title": "Medium alert", "summary": "Some info."},
        )

    assert result["notified"] is True
    mock_post.assert_called_once()


def test_missing_severity_treated_as_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """If severity is absent the event is treated as 'info' and skipped by default."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")

    result = send_notification.run("evt-004", {})

    assert result["notified"] is False


# ---------------------------------------------------------------------------
# Gotify unreachable — retry
# ---------------------------------------------------------------------------


def test_gotify_unreachable_triggers_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A RequestError from Gotify should trigger a Celery retry."""
    import httpx

    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry.side_effect = Exception("retried")

    with patch(
        "osint_core.workers.notify._post_to_gotify",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with pytest.raises(Exception, match="retried"):
            send_notification.run.__func__(
                mock_self,
                "evt-005",
                {"severity": "high", "title": "T", "summary": "S"},
            )

    mock_self.retry.assert_called_once()


# ---------------------------------------------------------------------------
# Missing token
# ---------------------------------------------------------------------------


def test_no_gotify_token_returns_not_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    """If OSINT_GOTIFY_TOKEN is unset the task should skip dispatch and return notified=False."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.delenv("OSINT_GOTIFY_TOKEN", raising=False)

    result = send_notification.run(
        "evt-006",
        {"severity": "critical", "title": "Critical!", "summary": "Very bad."},
    )

    # _post_to_gotify logs a warning and returns False when no token is set.
    assert result["notified"] is False
    assert result["event_id"] == "evt-006"


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


def test_return_shape_when_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    """The return dict must have event_id, notified, and reason keys."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    with patch("osint_core.workers.notify._post_to_gotify", return_value=True):
        result = send_notification.run(
            "evt-007",
            {"severity": "high", "title": "T", "summary": "S"},
        )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}


def test_return_shape_when_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The return dict must have event_id, notified, and reason keys when skipped."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "critical")

    result = send_notification.run(
        "evt-008",
        {"severity": "low"},
    )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}
    assert result["notified"] is False
