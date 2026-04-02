"""Tests for analyze_leads_task in prospecting worker."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_lead(*, analysis_status: str = "pending", lead_type: str = "policy") -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = lead_type
    lead.analysis_status = analysis_status
    lead.plan_id = "cal-prospecting"
    lead.event_ids = [uuid.uuid4()]
    lead.severity = "medium"
    return lead


def _make_event(*, minio_uri: str | None = "minio://bucket/key") -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.metadata_ = {"minio_uri": minio_uri} if minio_uri else {}
    event.raw_excerpt = "https://example.com"
    event.nlp_summary = "Summary"
    return event


class TestAnalyzeLeadsAsync:
    @pytest.mark.asyncio
    async def test_analyzes_pending_leads(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        lead = _make_lead()
        event = _make_event()
        analysis_result = {"actionable": True, "provisions": [{"section_reference": "\u00a71"}]}

        # Mock DB
        db = AsyncMock()
        # First execute: select plan version
        plan_result_mock = MagicMock()
        plan_version_mock = MagicMock()
        plan_version_mock.content = {
            "custom": {"deep_analysis_enabled": True, "precedent_map": {}},
        }
        plan_result_mock.scalar_one_or_none.return_value = plan_version_mock
        # Second execute: select pending leads
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = [lead]
        # Third execute: select event by id
        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event

        db.execute = AsyncMock(side_effect=[plan_result_mock, lead_result, event_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as mock_analyzer_cls,
        ):
            mock_instance = mock_analyzer_cls.return_value
            mock_instance.analyze_lead = AsyncMock(return_value=analysis_result)

            result = await _analyze_leads_async("cal-prospecting")

        assert result["analyzed"] >= 1
        assert lead.analysis_status == "completed"
        assert lead.deep_analysis == analysis_result

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        # Mock DB returning a plan with deep_analysis_enabled=False
        db = AsyncMock()
        plan_result_mock = MagicMock()
        plan_version_mock = MagicMock()
        plan_version_mock.content = {"custom": {"deep_analysis_enabled": False}}
        plan_result_mock.scalar_one_or_none.return_value = plan_version_mock
        db.execute = AsyncMock(return_value=plan_result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "skipped"
        assert result["reason"] == "deep_analysis_disabled"

    @pytest.mark.asyncio
    async def test_downgrades_non_actionable_leads(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        lead = _make_lead()
        lead.severity = "high"
        event = _make_event()
        analysis_result = {"actionable": False, "provisions": []}

        db = AsyncMock()
        plan_result_mock = MagicMock()
        plan_version_mock = MagicMock()
        plan_version_mock.content = {
            "custom": {"deep_analysis_enabled": True, "precedent_map": {}},
        }
        plan_result_mock.scalar_one_or_none.return_value = plan_version_mock
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = [lead]
        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event

        db.execute = AsyncMock(side_effect=[plan_result_mock, lead_result, event_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as mock_analyzer_cls,
        ):
            mock_instance = mock_analyzer_cls.return_value
            mock_instance.analyze_lead = AsyncMock(return_value=analysis_result)

            result = await _analyze_leads_async("cal-prospecting")

        assert result["analyzed"] >= 1
        assert lead.severity == "info"
        assert lead.analysis_status == "not_actionable"

    @pytest.mark.asyncio
    async def test_no_active_plan(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        db = AsyncMock()
        plan_result_mock = MagicMock()
        plan_result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=plan_result_mock)

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_plan"

    @pytest.mark.asyncio
    async def test_no_pending_leads(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        db = AsyncMock()
        plan_result_mock = MagicMock()
        plan_version_mock = MagicMock()
        plan_version_mock.content = {
            "custom": {"deep_analysis_enabled": True, "precedent_map": {}},
        }
        plan_result_mock.scalar_one_or_none.return_value = plan_version_mock
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[plan_result_mock, lead_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("osint_core.workers.prospecting.async_session", return_value=ctx):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "completed"
        assert result["analyzed"] == 0


class TestHelpers:
    def test_is_deep_analysis_enabled_true(self) -> None:
        from osint_core.workers.prospecting import _is_deep_analysis_enabled

        assert _is_deep_analysis_enabled({"custom": {"deep_analysis_enabled": True}}) is True

    def test_is_deep_analysis_enabled_false(self) -> None:
        from osint_core.workers.prospecting import _is_deep_analysis_enabled

        assert _is_deep_analysis_enabled({"custom": {"deep_analysis_enabled": False}}) is False

    def test_is_deep_analysis_enabled_none(self) -> None:
        from osint_core.workers.prospecting import _is_deep_analysis_enabled

        assert _is_deep_analysis_enabled(None) is False

    def test_is_deep_analysis_enabled_missing_key(self) -> None:
        from osint_core.workers.prospecting import _is_deep_analysis_enabled

        assert _is_deep_analysis_enabled({"custom": {}}) is False

    def test_get_precedent_map(self) -> None:
        from osint_core.workers.prospecting import _get_precedent_map

        pmap = {"4th_amendment": {"search": [{"case": "Terry v. Ohio"}]}}
        content = {"custom": {"precedent_map": pmap}}
        assert _get_precedent_map(content) == pmap

    def test_get_precedent_map_missing(self) -> None:
        from osint_core.workers.prospecting import _get_precedent_map

        assert _get_precedent_map({"custom": {}}) == {}


class TestPipelineGuard:
    def test_guard_checks_analysis_task_name(self) -> None:
        from osint_core.workers.prospecting import _has_pending_match_leads_tasks

        mock_inspector = MagicMock()
        mock_inspector.active.return_value = {
            "worker1": [{"name": "osint.analyze_leads", "id": "abc"}],
        }
        mock_inspector.reserved.return_value = {}

        with patch(
            "osint_core.workers.prospecting.celery_app.control.inspect",
            return_value=mock_inspector,
        ):
            assert _has_pending_match_leads_tasks() is True
