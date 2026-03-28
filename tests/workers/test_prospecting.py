"""Tests for prospecting worker tasks."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.prospecting import _match_leads_async


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
