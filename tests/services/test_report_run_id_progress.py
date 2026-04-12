"""Tests for run_id propagation and per-stage progress events (issue #312)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.prospecting_report import (
    ProspectingReportGenerator,
    ReportResult,
)

_MOD = "osint_core.services.prospecting_report"


def _make_lead(
    *,
    title: str = "Test Lead",
    analysis_status: str = "pending",
) -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = "incident"
    lead.status = "new"
    lead.title = title
    lead.summary = "Test summary"
    lead.constitutional_basis = ["1A-free-speech"]
    lead.jurisdiction = "CA"
    lead.institution = "UC Berkeley"
    lead.severity = "high"
    lead.confidence = 0.85
    lead.plan_id = "cal-prospecting"
    lead.event_ids = [uuid.uuid4()]
    lead.citations = {"sources": ["https://example.com/article"]}
    lead.reported_at = None
    lead.report_id = None
    lead.last_updated_at = datetime.now(UTC)
    lead.analysis_status = analysis_status
    lead.deep_analysis = None
    return lead


def _mock_db(leads: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = leads
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()

    async def _flush_side_effect() -> None:
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=_flush_side_effect)
    db.commit = AsyncMock()
    return db


class TestReportResultRunId:
    """ReportResult dataclass includes run_id field."""

    def test_report_result_has_run_id_field(self) -> None:
        result = ReportResult(
            pdf_bytes=b"%PDF",
            lead_count=1,
            artifact_uri="minio://test",
            report_date="April 12, 2026",
            run_id="abc-123",
        )
        assert result.run_id == "abc-123"

    @pytest.mark.asyncio()
    async def test_generate_report_returns_run_id(self) -> None:
        lead = _make_lead()
        db = _mock_db([lead])

        generator = ProspectingReportGenerator()
        with (
            patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"),
            patch(f"{_MOD}._archive_pdf", return_value="minio://ok"),
            patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"),
        ):
            result = await generator.generate_report(db)

        assert result is not None
        assert result.run_id is not None
        # run_id should be a valid UUID string
        uuid.UUID(result.run_id)


class TestPerStageProgressEvents:
    """report_pipeline_progress is emitted at each filtering stage."""

    @pytest.mark.asyncio()
    async def test_three_progress_events_emitted(self) -> None:
        lead = _make_lead()
        db = _mock_db([lead])

        generator = ProspectingReportGenerator()
        with (
            patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"),
            patch(f"{_MOD}._archive_pdf", return_value="minio://ok"),
            patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"),
            patch(f"{_MOD}.logger") as mock_logger,
        ):
            await generator.generate_report(db)

        progress_calls = [
            c for c in mock_logger.info.call_args_list
            if c.args and c.args[0] == "report_pipeline_progress"
        ]
        assert len(progress_calls) == 3

    @pytest.mark.asyncio()
    async def test_progress_events_have_correct_stages(self) -> None:
        lead = _make_lead()
        db = _mock_db([lead])

        generator = ProspectingReportGenerator()
        with (
            patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"),
            patch(f"{_MOD}._archive_pdf", return_value="minio://ok"),
            patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"),
            patch(f"{_MOD}.logger") as mock_logger,
        ):
            await generator.generate_report(db)

        progress_calls = [
            c for c in mock_logger.info.call_args_list
            if c.args and c.args[0] == "report_pipeline_progress"
        ]
        # First: selected stage
        assert "selected" in progress_calls[0].kwargs
        assert "stage" in progress_calls[0].kwargs
        assert progress_calls[0].kwargs["stage"] == "selected"

        # Second: reportable stage
        assert "reportable" in progress_calls[1].kwargs
        assert progress_calls[1].kwargs["stage"] == "reportable"

        # Third: rendered stage
        assert "rendered" in progress_calls[2].kwargs
        assert progress_calls[2].kwargs["stage"] == "rendered"
