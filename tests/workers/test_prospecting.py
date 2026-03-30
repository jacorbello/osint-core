"""Tests for prospecting worker tasks."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.lead_matcher import DEFAULT_CONFIDENCE_THRESHOLD
from osint_core.workers.prospecting import (
    _GUARD_BACKOFF_BASE,
    _GUARD_MAX_DEFERRALS,
    _build_matcher_config,
    _check_pipeline_guard,
    _generate_report_async,
    _has_pending_match_leads_tasks,
    _match_leads_async,
)


def _make_event(
    *,
    event_id: str | None = None,
    source_id: str = "rss_fire",
    title: str = "Professor fired for speech",
    severity: str | None = "medium",
    metadata: dict | None = None,
    plan_content: dict | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.UUID(event_id) if event_id else uuid.uuid4()
    event.source_id = source_id
    event.title = title
    event.severity = severity
    event.nlp_summary = "NLP summary"
    event.nlp_relevance = "relevant"
    event.summary = None

    if metadata is None:
        metadata = {
            "lead_type": "incident",
            "institution": "UC Berkeley",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech"],
            "affected_person": "Dr. Smith",
        }
    event.metadata_ = metadata

    event.plan_version = MagicMock()
    event.plan_version.plan_id = "cal-prospecting"
    event.plan_version.content = plan_content or {
        "scoring": {"source_reputation": {"rss_fire": 0.9}},
    }
    return event


def _mock_db_context(events):
    """Create a mock async_session context that returns given events."""
    db = AsyncMock()
    result_mock = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = events
    result_mock.scalars.return_value = scalars_mock
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()
    db.add = MagicMock()

    # Also mock the lead lookup (select Lead where fingerprint)
    # The LeadMatcher will call db.execute for lead lookup
    lead_result = MagicMock()
    lead_result.scalar_one_or_none.return_value = None

    # First call returns events, subsequent calls return lead lookup
    call_count = 0

    async def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return result_mock
        return lead_result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db


@pytest.mark.asyncio
async def test_processes_batch_creates_leads():
    """Task processes batch of events and creates leads."""
    event1 = _make_event()
    event2 = _make_event(
        source_id="x_cal_california",
        title="Student expelled for speech",
        metadata={
            "lead_type": "incident",
            "institution": "UCLA",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech"],
            "affected_person": "Student A",
        },
    )

    ctx, db = _mock_db_context([event1, event2])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
        result = await _match_leads_async(
            [str(event1.id), str(event2.id)], "cal-prospecting",
        )

    assert result["status"] == "completed"
    assert result["total"] == 2
    assert len(result["errors"]) == 0
    # Both events should have results
    assert str(event1.id) in result["results"]
    assert str(event2.id) in result["results"]


@pytest.mark.asyncio
async def test_error_in_one_event_doesnt_block_others():
    """Error processing one event shouldn't prevent processing others."""
    good_event = _make_event()

    # Use a dedicated mock subclass to avoid class-level property mutation
    class _BadMock(MagicMock):
        @property
        def metadata_(self):
            raise ValueError("boom")

    bad_event = _BadMock()
    bad_event.id = uuid.uuid4()
    bad_event.source_id = "rss_fire"
    bad_event.title = "Bad event"
    bad_event.severity = "medium"
    bad_event.nlp_summary = None
    bad_event.summary = None

    ctx, db = _mock_db_context([good_event, bad_event])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
        result = await _match_leads_async(
            [str(good_event.id), str(bad_event.id)], "cal-prospecting",
        )

    assert result["status"] == "completed"
    assert result["total"] == 2
    # Good event processed, bad event errored
    assert result["results"][str(good_event.id)] in ("created", "updated", "skipped")
    assert result["results"][str(bad_event.id)] == "error"
    assert str(bad_event.id) in result["errors"]


@pytest.mark.asyncio
async def test_no_events_found():
    """When no events found, returns no_events status."""
    ctx, db = _mock_db_context([])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
        result = await _match_leads_async([str(uuid.uuid4())], "cal-prospecting")

    assert result["status"] == "no_events"


@pytest.mark.asyncio
async def test_below_threshold_skips():
    """Events that don't meet confidence threshold are skipped."""
    event = _make_event(
        severity="info",
        metadata={"lead_type": "incident"},
    )

    ctx, db = _mock_db_context([event])

    # Use a very high threshold
    with patch("osint_core.workers.prospecting.async_session", return_value=ctx), \
         patch("osint_core.workers.prospecting.LeadMatcher") as mock_matcher_cls:
        mock_matcher = MagicMock()
        mock_matcher.match_event_to_lead = AsyncMock(return_value=None)
        mock_matcher_cls.return_value = mock_matcher

        result = await _match_leads_async([str(event.id)], "cal-prospecting")

    assert result["results"][str(event.id)] == "skipped"


@pytest.mark.asyncio
async def test_structlog_fields():
    """Verify logging includes lead_id and event_id."""
    event = _make_event()
    mock_lead = MagicMock()
    mock_lead.id = uuid.uuid4()
    mock_lead.event_ids = [event.id]

    ctx, db = _mock_db_context([event])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx), \
         patch("osint_core.workers.prospecting.LeadMatcher") as mock_matcher_cls, \
         patch("osint_core.workers.prospecting.logger") as mock_logger:
        mock_matcher = MagicMock()
        mock_matcher.match_event_to_lead = AsyncMock(return_value=mock_lead)
        mock_matcher_cls.return_value = mock_matcher

        await _match_leads_async([str(event.id)], "cal-prospecting")

    # Verify logging was called with lead_id and event_id in message
    mock_logger.info.assert_called()
    call_args = mock_logger.info.call_args
    log_msg = call_args[0][0] % call_args[0][1:]
    assert "lead_id=" in log_msg
    assert "event_id=" in log_msg


def test_build_matcher_config_reads_custom_threshold():
    """Config built with custom threshold from plan YAML."""
    plan_content = {
        "scoring": {"source_reputation": {"rss_fire": 0.9}},
        "custom": {"lead_confidence_threshold": 0.5},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == 0.5
    assert config.plan_id == "cal-prospecting"
    assert config.source_reputation == {"rss_fire": 0.9}


def test_build_matcher_config_default_when_no_custom():
    """Config uses default threshold when custom section is missing."""
    plan_content = {
        "scoring": {"source_reputation": {"rss_fire": 0.9}},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
    assert config.plan_id == "cal-prospecting"


def test_build_matcher_config_default_when_key_missing():
    """Config uses default threshold when custom exists but key is absent."""
    plan_content = {
        "scoring": {},
        "custom": {"other_setting": True},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD


def test_build_matcher_config_invalid_threshold_falls_back():
    """Non-numeric threshold falls back to default with warning."""
    plan_content = {
        "scoring": {},
        "custom": {"lead_confidence_threshold": "not-a-number"},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD


def test_build_matcher_config_out_of_range_threshold_falls_back():
    """Threshold outside 0.0-1.0 falls back to default with warning."""
    plan_content = {
        "scoring": {},
        "custom": {"lead_confidence_threshold": 5.0},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD


def test_build_matcher_config_string_threshold_cast_to_float():
    """Threshold from YAML may arrive as string; ensure it's cast to float."""
    plan_content = {
        "scoring": {},
        "custom": {"lead_confidence_threshold": "0.7"},
    }
    config = _build_matcher_config(plan_content, "cal-prospecting")
    assert config.confidence_threshold == 0.7
    assert isinstance(config.confidence_threshold, float)


@pytest.mark.asyncio
async def test_match_leads_no_plan_version_uses_defaults():
    """When no events have a plan_version, matcher uses default config."""
    event = _make_event()
    # Remove plan_version so the loop falls through without finding one
    event.plan_version = None

    ctx, db = _mock_db_context([event])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx), \
         patch("osint_core.workers.prospecting.LeadMatcher") as mock_matcher_cls:
        mock_matcher = MagicMock()
        mock_matcher.match_event_to_lead = AsyncMock(return_value=None)
        mock_matcher_cls.return_value = mock_matcher

        result = await _match_leads_async([str(event.id)], "cal-prospecting")

    assert result["status"] == "completed"
    # Verify matcher was constructed with default config (empty plan_content)
    config_arg = mock_matcher_cls.call_args[0][0]
    assert config_arg.plan_id == "cal-prospecting"
    assert config_arg.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
    assert config_arg.source_reputation == {}


@pytest.mark.asyncio
async def test_custom_threshold_passed_to_lead_matcher():
    """Plan-specified threshold is forwarded to LeadMatcher via config."""
    event = _make_event(
        plan_content={
            "scoring": {"source_reputation": {"rss_fire": 0.9}},
            "custom": {"lead_confidence_threshold": 0.8},
        },
    )

    ctx, db = _mock_db_context([event])

    with patch("osint_core.workers.prospecting.async_session", return_value=ctx), \
         patch("osint_core.workers.prospecting.LeadMatcher") as mock_matcher_cls:
        mock_matcher = MagicMock()
        mock_matcher.match_event_to_lead = AsyncMock(return_value=None)
        mock_matcher_cls.return_value = mock_matcher

        await _match_leads_async([str(event.id)], "cal-prospecting")

    # Verify LeadMatcher was constructed with the custom threshold
    config_arg = mock_matcher_cls.call_args[0][0]
    assert config_arg.confidence_threshold == 0.8


# ---------------------------------------------------------------------------
# Report generation / delivery tests
# ---------------------------------------------------------------------------


def _make_report_result(*, lead_count: int = 3) -> MagicMock:
    """Create a mock ReportResult returned by ProspectingReportGenerator."""
    result = MagicMock()
    result.pdf_bytes = b"%PDF-fake"
    result.lead_count = lead_count
    result.artifact_uri = "s3://osint-reports/prospecting/2026/03/30/report-080000.pdf"
    result.report_date = "March 30, 2026 — 08:00 AM CDT"
    return result


@pytest.mark.asyncio
async def test_resend_failure_still_archives_pdf():
    """If PDF generation succeeds but email fails, PDF is still archived and
    lead statuses are updated (done inside generate_report), while the email
    error propagates so the task can retry."""
    report_result = _make_report_result()

    mock_generator = MagicMock()
    mock_generator.generate_report = AsyncMock(return_value=report_result)

    mock_notifier = MagicMock()
    mock_notifier.send_report = AsyncMock(side_effect=ConnectionError("Resend down"))

    mock_settings = MagicMock()
    mock_settings.resend_recipients = "ops@example.com"

    mock_session_ctx = AsyncMock()
    mock_db = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_store = MagicMock()
    mock_store.get_active = AsyncMock(return_value=None)

    with patch(
        "osint_core.workers.prospecting.async_session",
        return_value=mock_session_ctx,
    ), patch(
        "osint_core.services.prospecting_report.ProspectingReportGenerator",
        return_value=mock_generator,
    ), patch(
        "osint_core.services.resend_notifier.ResendNotifier",
        return_value=mock_notifier,
    ), patch(
        "osint_core.services.plan_store.PlanStore",
        return_value=mock_store,
    ), patch(
        "osint_core.config.settings", mock_settings,
    ), patch(
        "osint_core.workers.prospecting.logger",
    ) as mock_logger, pytest.raises(ConnectionError, match="Resend down"):
        await _generate_report_async(0)

    # generate_report was called (PDF generated, archived, leads updated)
    mock_generator.generate_report.assert_awaited_once_with(mock_db)

    # Email delivery was attempted
    mock_notifier.send_report.assert_awaited_once()

    # Structured alert log was emitted
    mock_logger.error.assert_called_once()
    log_msg = mock_logger.error.call_args[0][0] % mock_logger.error.call_args[0][1:]
    assert "report_delivery_failed" in log_msg
    assert "plan_id=cal-prospecting" in log_msg
    assert "attempt=1" in log_msg
    assert "Resend down" in log_msg


@pytest.mark.asyncio
async def test_report_delivery_failed_log_includes_attempt_count():
    """The report_delivery_failed log event includes the correct attempt number."""
    report_result = _make_report_result()

    mock_generator = MagicMock()
    mock_generator.generate_report = AsyncMock(return_value=report_result)

    mock_notifier = MagicMock()
    mock_notifier.send_report = AsyncMock(side_effect=TimeoutError("timeout"))

    mock_settings = MagicMock()
    mock_settings.resend_recipients = "ops@example.com"

    mock_session_ctx = AsyncMock()
    mock_db = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_store = MagicMock()
    mock_store.get_active = AsyncMock(return_value=None)

    with patch(
        "osint_core.workers.prospecting.async_session",
        return_value=mock_session_ctx,
    ), patch(
        "osint_core.services.prospecting_report.ProspectingReportGenerator",
        return_value=mock_generator,
    ), patch(
        "osint_core.services.resend_notifier.ResendNotifier",
        return_value=mock_notifier,
    ), patch(
        "osint_core.services.plan_store.PlanStore",
        return_value=mock_store,
    ), patch(
        "osint_core.config.settings", mock_settings,
    ), patch(
        "osint_core.workers.prospecting.logger",
    ) as mock_logger, pytest.raises(TimeoutError):
        await _generate_report_async(2)

    log_msg = mock_logger.error.call_args[0][0] % mock_logger.error.call_args[0][1:]
    assert "attempt=3" in log_msg


@pytest.mark.asyncio
async def test_successful_report_delivery():
    """Happy path: PDF generated, archived, email sent successfully."""
    report_result = _make_report_result(lead_count=5)

    mock_generator = MagicMock()
    mock_generator.generate_report = AsyncMock(return_value=report_result)

    mock_notifier = MagicMock()
    mock_notifier.send_report = AsyncMock(return_value=True)

    mock_settings = MagicMock()
    mock_settings.resend_recipients = "ops@example.com,lead@example.com"

    mock_session_ctx = AsyncMock()
    mock_db = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_store = MagicMock()
    mock_store.get_active = AsyncMock(return_value=None)

    with patch(
        "osint_core.workers.prospecting.async_session",
        return_value=mock_session_ctx,
    ), patch(
        "osint_core.services.prospecting_report.ProspectingReportGenerator",
        return_value=mock_generator,
    ), patch(
        "osint_core.services.resend_notifier.ResendNotifier",
        return_value=mock_notifier,
    ), patch(
        "osint_core.services.plan_store.PlanStore",
        return_value=mock_store,
    ), patch(
        "osint_core.config.settings", mock_settings,
    ):
        result = await _generate_report_async()

    assert result["status"] == "completed"
    assert result["lead_count"] == 5
    assert result["email_sent"] is True
    assert result["artifact_uri"] == report_result.artifact_uri


def test_generate_report_task_max_retries():
    """Task max_retries includes guard deferrals plus generation retries."""
    from osint_core.workers.prospecting import generate_prospecting_report_task

    assert generate_prospecting_report_task.max_retries == 3 + _GUARD_MAX_DEFERRALS


# ---------------------------------------------------------------------------
# Pipeline completion guard tests
# ---------------------------------------------------------------------------


def test_has_pending_tasks_returns_true_when_active():
    """Guard detects active match_leads tasks."""
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = {
        "worker1@host": [
            {"name": "osint.match_leads", "id": "abc-123"},
        ],
    }
    mock_inspector.reserved.return_value = {}

    with patch("osint_core.workers.prospecting.celery_app") as mock_app:
        mock_app.control.inspect.return_value = mock_inspector
        assert _has_pending_match_leads_tasks() is True


def test_has_pending_tasks_returns_true_when_reserved():
    """Guard detects reserved (queued) match_leads tasks."""
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = {}
    mock_inspector.reserved.return_value = {
        "worker2@host": [
            {"name": "osint.match_leads", "id": "def-456"},
        ],
    }

    with patch("osint_core.workers.prospecting.celery_app") as mock_app:
        mock_app.control.inspect.return_value = mock_inspector
        assert _has_pending_match_leads_tasks() is True


def test_has_pending_tasks_returns_false_when_none_running():
    """Guard returns False when no match_leads tasks are active or reserved."""
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = {
        "worker1@host": [
            {"name": "osint.score_event", "id": "ghi-789"},
        ],
    }
    mock_inspector.reserved.return_value = {}

    with patch("osint_core.workers.prospecting.celery_app") as mock_app:
        mock_app.control.inspect.return_value = mock_inspector
        assert _has_pending_match_leads_tasks() is False


def test_has_pending_tasks_returns_false_when_inspector_returns_none():
    """Guard returns False when workers are unreachable (inspect returns None)."""
    mock_inspector = MagicMock()
    mock_inspector.active.return_value = None
    mock_inspector.reserved.return_value = None

    with patch("osint_core.workers.prospecting.celery_app") as mock_app:
        mock_app.control.inspect.return_value = mock_inspector
        assert _has_pending_match_leads_tasks() is False


def test_report_deferred_when_match_leads_pending():
    """Guard returns should_defer=True when match_leads tasks are still running."""
    with patch(
        "osint_core.workers.prospecting._has_pending_match_leads_tasks",
        return_value=True,
    ):
        result = _check_pipeline_guard(headers=None)

    assert result.should_defer is True
    assert result.deferrals == 1
    assert result.countdown == _GUARD_BACKOFF_BASE  # base * 1


def test_report_deferred_increments_deferral_count():
    """Guard increments deferral counter with increasing backoff."""
    with patch(
        "osint_core.workers.prospecting._has_pending_match_leads_tasks",
        return_value=True,
    ):
        result = _check_pipeline_guard(headers={"x_guard_deferrals": 2})

    assert result.should_defer is True
    assert result.deferrals == 3
    assert result.countdown == _GUARD_BACKOFF_BASE * 3


def test_report_proceeds_when_no_pending_tasks():
    """Guard returns should_defer=False when no match_leads tasks are pending."""
    with patch(
        "osint_core.workers.prospecting._has_pending_match_leads_tasks",
        return_value=False,
    ):
        result = _check_pipeline_guard(headers=None)

    assert result.should_defer is False
    assert result.deferrals == 0


def test_guard_exhausted_proceeds_with_warning():
    """After max deferrals, guard returns should_defer=False despite pending tasks."""
    with patch(
        "osint_core.workers.prospecting._has_pending_match_leads_tasks",
        return_value=True,
    ), patch(
        "osint_core.workers.prospecting.logger",
    ) as mock_logger:
        result = _check_pipeline_guard(
            headers={"x_guard_deferrals": _GUARD_MAX_DEFERRALS},
        )

    assert result.should_defer is False
    assert result.deferrals == _GUARD_MAX_DEFERRALS
    # Warning log was emitted about guard exhaustion
    mock_logger.warning.assert_called()
    warn_msg = mock_logger.warning.call_args[0][0]
    assert "pipeline_guard_exhausted" in warn_msg


def test_guard_countdown_capped_at_600():
    """Guard countdown is capped at 600 seconds."""
    with patch(
        "osint_core.workers.prospecting._has_pending_match_leads_tasks",
        return_value=True,
    ):
        result = _check_pipeline_guard(
            headers={"x_guard_deferrals": _GUARD_MAX_DEFERRALS - 1},
        )

    assert result.should_defer is True
    assert result.countdown <= 600
