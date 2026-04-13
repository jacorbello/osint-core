"""Tests for _analyze_leads_async database commit failure handling."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from osint_core.workers.prospecting import _analyze_leads_async


def _make_plan_version(*, enabled: bool = True) -> MagicMock:
    pv = MagicMock()
    pv.content = {
        "custom": {"deep_analysis_enabled": enabled},
    }
    pv.is_active = True
    return pv


def _make_lead(*, analysis_status: str = "pending") -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.plan_id = "plan-1"
    lead.analysis_status = analysis_status
    lead.event_ids = [uuid.uuid4()]
    lead.title = "Test lead"
    lead.deep_analysis = None
    lead.severity = None
    lead.citations = None
    return lead


def _make_event() -> MagicMock:
    evt = MagicMock()
    evt.id = uuid.uuid4()
    evt.source_id = "rss_fire"
    evt.title = "Test event"
    evt.raw_excerpt = "excerpt"
    evt.created_at = "2026-01-01"
    evt.metadata_ = {"url": "https://example.gov/doc"}
    return evt


def _build_db_mock(
    plan_version: MagicMock,
    leads: list[MagicMock],
    event: MagicMock,
    commit_error: Exception | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """Build a mock async_session that returns plan, leads, and event in order."""
    db = AsyncMock()

    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = plan_version

    leads_result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = leads
    leads_result.scalars.return_value = scalars_mock

    event_result = MagicMock()
    event_result.scalar_one_or_none.return_value = event

    call_count = 0

    async def execute_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return plan_result
        if call_count == 2:
            return leads_result
        return event_result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.add = MagicMock()
    db.rollback = AsyncMock()

    if commit_error:
        db.commit = AsyncMock(side_effect=commit_error)
    else:
        db.commit = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, db


class TestAnalyzeLeadsCommitFailure:
    @pytest.mark.asyncio
    async def test_commit_failure_propagates(self) -> None:
        """SQLAlchemyError on commit propagates, enabling Celery retry."""
        pv = _make_plan_version()
        lead = _make_lead()
        event = _make_event()
        ctx, db = _build_db_mock(pv, [lead], event, commit_error=SQLAlchemyError("disk full"))

        analyze_result = {"provisions": [], "actionable": True, "analysis_status": "completed"}
        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as mock_analyzer_cls,
        ):
            mock_analyzer_cls.return_value.analyze_lead = AsyncMock(return_value=analyze_result)
            mock_analyzer_cls.compute_max_severity = MagicMock(return_value="medium")
            mock_analyzer_cls.build_citations = MagicMock(return_value=[])

            with pytest.raises(SQLAlchemyError, match="disk full"):
                await _analyze_leads_async("plan-1")

    @pytest.mark.asyncio
    async def test_commit_failure_no_partial_status(self) -> None:
        """db.commit() is called once at the end, so failure rolls back all updates."""
        pv = _make_plan_version()
        lead = _make_lead()
        initial_status = lead.analysis_status
        event = _make_event()
        ctx, db = _build_db_mock(pv, [lead], event, commit_error=SQLAlchemyError("oops"))

        analyze_result = {"provisions": [], "actionable": True, "analysis_status": "completed"}
        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as mock_analyzer_cls,
        ):
            mock_analyzer_cls.return_value.analyze_lead = AsyncMock(return_value=analyze_result)
            mock_analyzer_cls.compute_max_severity = MagicMock(return_value="medium")
            mock_analyzer_cls.build_citations = MagicMock(return_value=[])

            with pytest.raises(SQLAlchemyError):
                await _analyze_leads_async("plan-1")

        db.commit.assert_called_once()
        # Verify analysis_status was mutated in memory (would be rolled back by
        # the real async session context manager on commit failure).
        assert initial_status == "pending"
        assert lead.analysis_status != initial_status, (
            "analysis_status should have been mutated in-memory before the failed commit"
        )

    @pytest.mark.asyncio
    async def test_commit_failure_multiple_leads(self) -> None:
        """With multiple leads, all are processed in one transaction."""
        pv = _make_plan_version()
        leads = [_make_lead(), _make_lead()]
        event = _make_event()
        ctx, db = _build_db_mock(pv, leads, event, commit_error=SQLAlchemyError("timeout"))

        analyze_result = {"provisions": [], "actionable": True, "analysis_status": "completed"}
        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as mock_analyzer_cls,
        ):
            mock_analyzer_cls.return_value.analyze_lead = AsyncMock(return_value=analyze_result)
            mock_analyzer_cls.compute_max_severity = MagicMock(return_value="medium")
            mock_analyzer_cls.build_citations = MagicMock(return_value=[])

            with pytest.raises(SQLAlchemyError, match="timeout"):
                await _analyze_leads_async("plan-1")

        db.commit.assert_called_once()
        # Every lead should have been mutated in-memory before the failed commit;
        # none should still be in the initial "pending" state.
        for lead in leads:
            assert lead.analysis_status != "pending", (
                f"Lead {lead.id} analysis_status should have been mutated before commit"
            )
