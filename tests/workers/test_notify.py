"""Tests for the Celery notification worker task."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.notify import (
    _needs_db_fetch,
    send_notification,
)

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
# _needs_db_fetch helper
# ---------------------------------------------------------------------------


def test_needs_db_fetch_none():
    """None event_data should trigger DB fetch."""
    assert _needs_db_fetch(None) is True


def test_needs_db_fetch_empty_dict():
    """Empty dict should trigger DB fetch."""
    assert _needs_db_fetch({}) is True


def test_needs_db_fetch_partial_data():
    """Dict missing required fields should trigger DB fetch."""
    assert _needs_db_fetch({"severity": "high", "title": "T"}) is True


def test_needs_db_fetch_none_values():
    """Dict with None values for required fields should trigger DB fetch."""
    data = {"severity": "high", "title": None, "summary": "S", "source_id": "x"}
    assert _needs_db_fetch(data) is True


def test_needs_db_fetch_complete_data():
    """Dict with all required fields should not trigger DB fetch."""
    assert _needs_db_fetch({
        "severity": "high",
        "title": "T",
        "summary": "S",
        "source_id": "nvd",
    }) is False


# ---------------------------------------------------------------------------
# Threshold / skip logic
# ---------------------------------------------------------------------------


def test_below_threshold_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events below the configured threshold should not trigger a notification."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "high")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "test-token")

    result = send_notification.run(
        "evt-001",
        {"severity": "low", "title": "Minor event", "summary": "Nothing to see here.",
         "source_id": "test"},
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
            {"severity": "medium", "title": "Medium alert", "summary": "Some info.",
             "source_id": "test"},
        )

    assert result["notified"] is True
    mock_post.assert_called_once()


def test_missing_severity_treated_as_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """If severity is absent the event is treated as 'info' and skipped by default."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "medium")

    # Provide complete data to avoid DB fetch attempt.
    result = send_notification.run("evt-004", {
        "title": "T", "summary": "S", "source_id": "x", "severity": None,
    })

    assert result["notified"] is False


# ---------------------------------------------------------------------------
# DB fallback — event_data is None
# ---------------------------------------------------------------------------


def test_db_fetch_when_event_data_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data is None, the task should fetch from DB and use those fields."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    db_data = {
        "title": "DB Title",
        "summary": "DB Summary",
        "severity": "high",
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-1234"],
    }

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=db_data,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-1", None)

    assert result["notified"] is True
    assert result["event_id"] == "evt-db-1"
    mock_post.assert_called_once()


def test_db_fetch_supplements_missing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data is missing title/summary, DB data should supplement."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    # Caller provides severity but no title/summary.
    partial_data = {"severity": "critical"}

    db_data = {
        "title": "DB Title",
        "summary": "DB Summary",
        "severity": "high",  # Should NOT overwrite caller's "critical".
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-5678"],
    }

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=db_data,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-2", partial_data)

    assert result["notified"] is True
    # Priority should be 10 for "critical" (caller's severity, not DB's "high").
    call_args = mock_post.call_args
    assert call_args.args[2] == 10


def test_db_fetch_failure_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DB fetch fails, task should fall back to available data gracefully."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=None,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify:
        # event_data=None and DB returns None — still works with defaults.
        result = send_notification.run("evt-db-3", None)

    # Severity falls back to "info" which is below "low" threshold.
    assert result["notified"] is False
    assert result["event_id"] == "evt-db-3"


def test_db_fetch_failure_graceful_with_partial_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DB fetch fails but partial data exists, task uses what it has."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    partial = {"severity": "high"}

    mock_fetch = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock, return_value=None,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch, mock_gotify as mock_post:
        result = send_notification.run("evt-db-4", partial)

    assert result["notified"] is True
    assert result["event_id"] == "evt-db-4"
    mock_post.assert_called_once()


def test_no_db_fetch_when_data_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """When event_data has all required fields, no DB fetch should happen."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "low")
    monkeypatch.setenv("OSINT_GOTIFY_TOKEN", "tok")

    complete_data = {
        "severity": "high",
        "title": "Complete Title",
        "summary": "Complete Summary",
        "source_id": "nvd",
        "event_type": "cve",
        "indicators": ["CVE-2026-0001"],
    }

    mock_fetch_p = patch(
        "osint_core.workers.notify._fetch_event_data",
        new_callable=AsyncMock,
    )
    mock_gotify = patch(
        "osint_core.workers.notify._post_to_gotify", return_value=True,
    )
    with mock_fetch_p as mock_fetch, mock_gotify:
        result = send_notification.run("evt-db-5", complete_data)

    mock_fetch.assert_not_called()
    assert result["notified"] is True


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
    ), pytest.raises(Exception, match="retried"):
        send_notification.run.__func__(
            mock_self,
            "evt-005",
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
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
        {"severity": "critical", "title": "Critical!", "summary": "Very bad.",
         "source_id": "test"},
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
            {"severity": "high", "title": "T", "summary": "S", "source_id": "x"},
        )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}


def test_return_shape_when_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The return dict must have event_id, notified, and reason keys when skipped."""
    monkeypatch.setenv("OSINT_NOTIFY_THRESHOLD", "critical")

    result = send_notification.run(
        "evt-008",
        {"severity": "low", "title": "T", "summary": "S", "source_id": "x"},
    )

    assert set(result.keys()) >= {"event_id", "notified", "reason"}
    assert result["notified"] is False
