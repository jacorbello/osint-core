"""Tests for the Celery digest compilation worker task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.digest import (
    _build_digest_markdown,
    _build_severity_breakdown,
    _build_source_breakdown,
    _compile_digest_async,
    _window_hours,
    compile_digest,
)

# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_compile_digest_task_registered():
    """The compile_digest task should be registered with the correct name."""
    assert compile_digest.name == "osint.compile_digest"


def test_compile_digest_task_max_retries():
    """The compile_digest task should have max_retries=3."""
    assert compile_digest.max_retries == 3


def test_compile_digest_is_bound():
    """The compile_digest task should be a bound task (bind=True)."""
    assert compile_digest.__bound__ is True


# ---------------------------------------------------------------------------
# _window_hours helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "hours", "expected"),
    [
        ("daily", None, 24),
        ("weekly", None, 168),
        ("shift", None, 8),
        ("daily", 12, 12),
        ("unknown", None, 24),
        ("daily", 0, 24),  # zero treated as "not provided"
    ],
)
def test_window_hours(period: str, hours: int | None, expected: int) -> None:
    assert _window_hours(period, hours) == expected


# ---------------------------------------------------------------------------
# _build_severity_breakdown helper
# ---------------------------------------------------------------------------


def test_severity_breakdown_empty():
    assert _build_severity_breakdown([]) == {}


def test_severity_breakdown_single_severity():
    events = [{"severity": "high"}, {"severity": "high"}]
    assert _build_severity_breakdown(events) == {"high": 2}


def test_severity_breakdown_mixed():
    events = [
        {"severity": "critical"},
        {"severity": "high"},
        {"severity": "critical"},
        {"severity": "low"},
        {},  # missing severity defaults to "info"
    ]
    result = _build_severity_breakdown(events)
    assert result["critical"] == 2
    assert result["high"] == 1
    assert result["low"] == 1
    assert result["info"] == 1


def test_severity_breakdown_none_severity():
    events = [{"severity": None}]
    assert _build_severity_breakdown(events) == {"info": 1}


# ---------------------------------------------------------------------------
# _build_source_breakdown helper
# ---------------------------------------------------------------------------


def test_source_breakdown_empty():
    assert _build_source_breakdown([]) == {}


def test_source_breakdown_mixed():
    events = [
        {"source_id": "nvd"},
        {"source_id": "rss:bbc"},
        {"source_id": "nvd"},
        {},  # missing source_id -> "unknown"
    ]
    result = _build_source_breakdown(events)
    assert result["nvd"] == 2
    assert result["rss:bbc"] == 1
    assert result["unknown"] == 1


# ---------------------------------------------------------------------------
# _build_digest_markdown helper
# ---------------------------------------------------------------------------


def test_build_digest_markdown_contains_plan_id():
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    window_start = now - timedelta(hours=24)
    events: list[dict[str, Any]] = [
        {"event_id": str(uuid.uuid4()), "severity": "high", "source_id": "nvd"},
    ]
    severity_breakdown = {"high": 1}
    md = _build_digest_markdown(
        "plan-abc", "daily", now, window_start, events, severity_breakdown,
    )
    assert "plan-abc" in md
    assert "Daily" in md
    assert "1 high" in md
    assert "**Total events:** 1" in md


def test_build_digest_markdown_multiple_severities():
    now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    window_start = now - timedelta(hours=24)
    events: list[dict[str, Any]] = [{"event_id": str(uuid.uuid4())} for _ in range(3)]
    severity_breakdown = {"critical": 1, "high": 2}
    md = _build_digest_markdown(
        "plan-xyz", "weekly", now, window_start, events, severity_breakdown,
    )
    assert "1 critical" in md
    assert "2 high" in md
    assert "**Total events:** 3" in md


# ---------------------------------------------------------------------------
# Helpers for DB-mocked async tests
# ---------------------------------------------------------------------------


def _make_mock_event(
    event_id=None,
    severity="high",
    source_id="nvd",
    title="Test event",
    occurred_at=None,
):
    """Create a mock Event ORM object."""
    evt = MagicMock()
    evt.id = event_id or uuid.uuid4()
    evt.severity = severity
    evt.source_id = source_id
    evt.title = title
    evt.occurred_at = occurred_at
    evt.metadata_ = {}
    return evt


def _make_mock_plan(plan_id="plan-abc", email_to="admin@example.com"):
    """Create a mock PlanVersion ORM object with email notification config."""
    plan = MagicMock()
    plan.plan_id = plan_id
    plan.is_active = True
    plan.content = {
        "notifications": {
            "routes": [
                {
                    "name": "default",
                    "channels": [
                        {"type": "email", "to": email_to},
                    ],
                },
            ],
        },
    }
    return plan


def _make_mock_db(events_orm, brief_id=None, plan=None, *, pdf_path=False):
    """Build an AsyncMock DB session that returns the given events.

    Args:
        events_orm: List of mock Event ORM objects.
        brief_id: Optional UUID to assign to the Brief record.
        plan: Optional mock PlanVersion returned by the plan-lookup query.
        pdf_path: When ``True`` the PDF-update DB query is expected
            (i.e. ``generate_and_upload_pdf`` is patched successfully).
    """
    mock_event_result = MagicMock()
    mock_event_result.scalars.return_value.all.return_value = events_orm

    # Result for the PDF-update query.
    mock_brief_result = MagicMock()
    mock_brief_result.scalar_one_or_none.return_value = MagicMock()

    # Result for the plan-lookup query.
    mock_plan_result = MagicMock()
    mock_plan_result.scalar_one_or_none.return_value = plan

    mock_db = AsyncMock()
    # execute is called multiple times across different async-session scopes.
    # Because the same mock_db is returned by the patched async_session
    # factory each time, we use side_effect to return the right result for
    # each successive call.
    if events_orm:
        results: list[Any] = [mock_event_result]
        if pdf_path:
            results.append(mock_brief_result)
        results.append(mock_plan_result)
        mock_db.execute = AsyncMock(side_effect=results)
    else:
        mock_db.execute = AsyncMock(return_value=mock_event_result)

    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(
        side_effect=lambda obj: setattr(obj, "id", brief_id or uuid.uuid4()),
    )
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    return mock_db


# ---------------------------------------------------------------------------
# _compile_digest_async -- DB integration (mocked)
# ---------------------------------------------------------------------------


class TestCompileDigestAsync:
    """Tests for the async digest compilation with mocked DB."""

    @pytest.mark.asyncio
    async def test_empty_result_when_no_events(self):
        """Returns status=empty when no events match the query."""
        mock_db = _make_mock_db([])
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", None, False)

        assert result["status"] == "empty"
        assert result["alert_count"] == 0
        assert result["digest_id"] is None
        assert result["plan_id"] == "plan-abc"

    @pytest.mark.asyncio
    async def test_creates_brief_and_marks_digested(self):
        """Creates a Brief record and marks events as digested."""
        evt1 = _make_mock_event(severity="critical", source_id="nvd", title="CVE-2026-1234")
        evt2 = _make_mock_event(severity="high", source_id="rss:bbc", title="Attack report")
        brief_id = uuid.uuid4()
        mock_db = _make_mock_db([evt1, evt2], brief_id)
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-xyz", "daily", None, False)

        assert result["status"] == "ok"
        assert result["alert_count"] == 2
        assert result["digest_id"] == str(brief_id)
        assert result["severity_breakdown"]["critical"] == 1
        assert result["severity_breakdown"]["high"] == 1
        assert result["source_breakdown"]["nvd"] == 1
        assert result["source_breakdown"]["rss:bbc"] == 1

        # Verify Brief was added to the session
        mock_db.add.assert_called_once()
        added_brief = mock_db.add.call_args[0][0]
        assert added_brief.generated_by == "digest"
        assert added_brief.title == "Digest: plan-xyz (daily)"

        # Verify events were marked as digested
        assert evt1.metadata_["digested"] is True
        assert evt2.metadata_["digested"] is True

        # Verify commit was called
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chains_notification_when_notify_true(self):
        """Chains send_notification.delay when notify=True and digest exists."""
        evt = _make_mock_event()
        brief_id = uuid.uuid4()
        plan = _make_mock_plan(plan_id="plan-abc", email_to="ops@example.com")
        mock_db = _make_mock_db([evt], brief_id, plan=plan)
        mock_self = MagicMock()
        mock_send = MagicMock()

        with (
            patch("osint_core.workers.digest.async_session", return_value=mock_db),
            patch("osint_core.workers.notify.send_notification", mock_send),
        ):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", None, True)

        assert result["status"] == "ok"
        assert result["digest_id"] == str(brief_id)
        mock_send.delay.assert_called_once()
        call_kwargs = mock_send.delay.call_args
        # event_id should be the digest_id (Brief ID) so filenames are stable.
        assert call_kwargs.args[0] == str(brief_id)
        # event_data should contain digest metadata.
        ed = call_kwargs.kwargs["event_data"]
        assert "Digest:" in ed["title"]
        assert ed["source_id"] == "plan-abc"
        assert ed["severity"] in ("info", "low", "medium", "high", "critical")
        assert ed["digest_id"] == str(brief_id)
        assert call_kwargs.kwargs["pdf_uri"] is None
        # channels should include the plan's email config with the "to" field.
        channels = call_kwargs.kwargs["channels"]
        assert any(ch.get("to") == "ops@example.com" for ch in channels)

    @pytest.mark.asyncio
    async def test_no_notification_when_notify_false(self):
        """Does not chain notification when notify=False."""
        evt = _make_mock_event()
        brief_id = uuid.uuid4()
        mock_db = _make_mock_db([evt], brief_id)
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", None, False)

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_custom_hours_override(self):
        """Explicit hours parameter overrides the period default."""
        mock_db = _make_mock_db([])
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", 48, False)

        assert result["window_hours"] == 48

    @pytest.mark.asyncio
    async def test_weekly_window(self):
        """Weekly period uses 168-hour window."""
        mock_db = _make_mock_db([])
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-abc", "weekly", None, False)

        assert result["window_hours"] == 168

    @pytest.mark.asyncio
    async def test_event_ids_in_brief(self):
        """Brief record receives correct event_ids array."""
        evt1 = _make_mock_event()
        evt2 = _make_mock_event()
        mock_db = _make_mock_db([evt1, evt2])
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            await _compile_digest_async(mock_self, "plan-abc", "daily", None, False)

        added_brief = mock_db.add.call_args[0][0]
        assert evt1.id in added_brief.event_ids
        assert evt2.id in added_brief.event_ids

    @pytest.mark.asyncio
    async def test_chains_notification_with_pdf_uri(self):
        """When PDF generation succeeds, pdf_uri is forwarded to send_notification."""
        evt = _make_mock_event()
        brief_id = uuid.uuid4()
        plan = _make_mock_plan(plan_id="plan-abc")
        mock_db = _make_mock_db([evt], brief_id, plan=plan, pdf_path=True)
        mock_self = MagicMock()
        mock_send = MagicMock()

        pdf_uri = f"minio://osint-briefs/briefs/{brief_id}.pdf"

        with (
            patch("osint_core.workers.digest.async_session", return_value=mock_db),
            patch("osint_core.workers.notify.send_notification", mock_send),
            patch(
                "osint_core.services.pdf_export.generate_and_upload_pdf",
                return_value=pdf_uri,
            ),
        ):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", None, True)

        assert result["status"] == "ok"
        assert result.get("pdf_uri") == pdf_uri
        mock_send.delay.assert_called_once()
        call_kwargs = mock_send.delay.call_args
        assert call_kwargs.args[0] == str(brief_id)
        assert call_kwargs.kwargs["pdf_uri"] == pdf_uri
        ed = call_kwargs.kwargs["event_data"]
        assert ed["metadata"]["pdf_uri"] == pdf_uri
        assert ed["digest_id"] == str(brief_id)

    @pytest.mark.asyncio
    async def test_iso8601_timestamps(self):
        """Window timestamps are valid ISO-8601."""
        mock_db = _make_mock_db([])
        mock_self = MagicMock()

        with patch("osint_core.workers.digest.async_session", return_value=mock_db):
            result = await _compile_digest_async(mock_self, "plan-abc", "daily", None, False)

        # Should not raise
        datetime.fromisoformat(result["window_start"])
        datetime.fromisoformat(result["window_end"])
