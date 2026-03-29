"""Tests for prospecting report and collection scheduling tasks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.prospecting import (
    _collect_sources_async,
    _generate_report_async,
)


@pytest.fixture()
def mock_report_result() -> MagicMock:
    result = MagicMock()
    result.pdf_bytes = b"%PDF-fake"
    result.lead_count = 3
    result.artifact_uri = "minio://osint-reports/prospecting/2026/03/29/report-130000.pdf"
    result.report_date = "March 29, 2026 — 08:00 AM CDT"
    return result


class TestGenerateReportTask:
    """Tests for generate_prospecting_report_task."""

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_skips_when_no_leads(self, mock_session: MagicMock) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "osint_core.services.prospecting_report.ProspectingReportGenerator",
            autospec=True,
        ) as mock_gen_cls:
            mock_gen_cls.return_value.generate_report = AsyncMock(return_value=None)
            result = await _generate_report_async()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_new_leads"

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_skips_when_no_recipients(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_settings.resend_recipients = ""
            result = await _generate_report_async()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_recipients"
        assert result["lead_count"] == 3

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_generates_and_sends_report(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_settings.resend_recipients = "alice@example.com,bob@example.com"

            result = await _generate_report_async()

        assert result["status"] == "completed"
        assert result["lead_count"] == 3
        assert result["email_sent"] is True

        # Verify notifier was called with correct args
        mock_notifier_cls.return_value.send_report.assert_awaited_once()
        call_kwargs = mock_notifier_cls.return_value.send_report.call_args
        assert call_kwargs.kwargs["pdf_bytes"] == b"%PDF-fake"
        assert call_kwargs.kwargs["recipients"] == ["alice@example.com", "bob@example.com"]

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_report_calls_generator_then_notifier(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Verify generator is called before notifier (correct order)."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        call_order: list[str] = []

        async def track_generate(*args: object, **kwargs: object) -> MagicMock:
            call_order.append("generate")
            return mock_report_result

        async def track_send(*args: object, **kwargs: object) -> bool:
            call_order.append("send")
            return True

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = track_generate
            mock_notifier_cls.return_value.send_report = track_send
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        assert call_order == ["generate", "send"]


class TestCollectSourcesTask:
    """Tests for collect_prospecting_sources_task."""

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_skips_when_no_plan(self, mock_session: MagicMock) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "osint_core.services.plan_store.PlanStore",
            autospec=True,
        ) as mock_store_cls:
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            result = await _collect_sources_async("cal-prospecting")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_plan"

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_dispatches_ingest_for_sources(self, mock_session: MagicMock) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_plan = MagicMock()
        mock_plan.content = {
            "sources": [
                {"id": "rss_fire", "type": "rss"},
                {"id": "x_cal_california", "type": "xai_x_search"},
                {"id": "univ_uc", "type": "university_policy"},
            ],
        }

        with (
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch(
                "osint_core.workers.ingest.ingest_source",
            ) as mock_ingest,
        ):
            mock_store_cls.return_value.get_active = AsyncMock(return_value=mock_plan)
            result = await _collect_sources_async("cal-prospecting")

        assert result["status"] == "completed"
        assert result["sources_dispatched"] == 3
        assert mock_ingest.delay.call_count == 3

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_skips_when_no_sources(self, mock_session: MagicMock) -> None:
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_plan = MagicMock()
        mock_plan.content = {"sources": []}

        with patch(
            "osint_core.services.plan_store.PlanStore",
            autospec=True,
        ) as mock_store_cls:
            mock_store_cls.return_value.get_active = AsyncMock(return_value=mock_plan)
            result = await _collect_sources_async("cal-prospecting")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_sources"
