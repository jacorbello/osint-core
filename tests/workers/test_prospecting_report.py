"""Tests for prospecting report and collection scheduling tasks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core import metrics
from osint_core.workers.prospecting import (
    _EMAIL_MAX_RETRIES,
    _collect_sources_async,
    _generate_report_async,
    _resolve_recipients,
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

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(return_value=None)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            result = await _generate_report_async()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_new_leads"
        # PlanStore should not be called when there are no leads (early return)
        mock_store_cls.return_value.get_active.assert_not_awaited()

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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            # No plan-level recipients, no global recipients
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = ""
            result = await _generate_report_async()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_recipients"
        assert result["lead_count"] == 3

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_generates_and_sends_report_global_fallback(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Global settings recipients are used when plan has no recipients."""
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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            # Plan has no resend recipients configured
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "alice@example.com,bob@example.com"

            result = await _generate_report_async()

        assert result["status"] == "completed"
        assert result["lead_count"] == 3
        assert result["email_sent"] is True

        # Verify notifier was called with global config recipients
        mock_notifier_cls.return_value.send_report.assert_awaited_once()
        call_kwargs = mock_notifier_cls.return_value.send_report.call_args
        assert call_kwargs.kwargs["pdf_bytes"] == b"%PDF-fake"
        assert call_kwargs.kwargs["recipients"] == ["alice@example.com", "bob@example.com"]

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_generates_and_sends_report_plan_recipients(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Plan-level recipients take priority over global settings."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_plan = MagicMock()
        mock_plan.content = {
            "custom": {
                "resend": {
                    "recipients": ["plan-user@example.com", "plan-admin@example.com"],
                },
            },
        }

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=mock_plan)
            # Global config should be ignored when plan has recipients
            mock_settings.resend_recipients = "global@example.com"

            result = await _generate_report_async()

        assert result["status"] == "completed"
        assert result["lead_count"] == 3
        assert result["email_sent"] is True

        # Verify notifier was called with plan-level recipients, not global
        mock_notifier_cls.return_value.send_report.assert_awaited_once()
        call_kwargs = mock_notifier_cls.return_value.send_report.call_args
        assert call_kwargs.kwargs["recipients"] == [
            "plan-user@example.com",
            "plan-admin@example.com",
        ]

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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = track_generate
            mock_notifier_cls.return_value.send_report = track_send
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        assert call_order == ["generate", "send"]

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.asyncio.sleep", new_callable=AsyncMock)
    @patch("osint_core.workers.prospecting.async_session")
    async def test_retries_email_on_first_failure_succeeds_on_second(
        self,
        mock_session: MagicMock,
        mock_sleep: AsyncMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Email delivery is retried when send_report returns False, and
        succeeds on the second attempt without regenerating the PDF."""
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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            # First call returns False (failure), second returns True (success)
            mock_notifier_cls.return_value.send_report = AsyncMock(
                side_effect=[False, True],
            )
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            result = await _generate_report_async()

        assert result["status"] == "completed"
        assert result["email_sent"] is True
        # PDF generation called only once (no regeneration on email retry)
        mock_gen_cls.return_value.generate_report.assert_awaited_once()
        # send_report called twice (first fail, second success)
        assert mock_notifier_cls.return_value.send_report.await_count == 2
        # Backoff sleep was called once between attempts
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.asyncio.sleep", new_callable=AsyncMock)
    @patch("osint_core.workers.prospecting.async_session")
    async def test_email_exhaustion_emits_alert_event(
        self,
        mock_session: MagicMock,
        mock_sleep: AsyncMock,
        mock_report_result: MagicMock,
    ) -> None:
        """After all email retries are exhausted, a report_email_exhausted
        log event is emitted and the result has email_sent=False."""
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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
            patch("osint_core.workers.prospecting.logger") as mock_logger,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            # All attempts return False
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=False)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            result = await _generate_report_async()

        assert result["status"] == "completed"
        assert result["email_sent"] is False
        # send_report called exactly _EMAIL_MAX_RETRIES times
        assert mock_notifier_cls.return_value.send_report.await_count == _EMAIL_MAX_RETRIES
        # Verify the exhaustion alert was logged
        exhaustion_calls = [
            call
            for call in mock_logger.error.call_args_list
            if "report_email_exhausted" in str(call)
        ]
        assert len(exhaustion_calls) == 1


class TestResolveRecipients:
    """Tests for _resolve_recipients helper."""

    def test_plan_recipients_used_when_present(self) -> None:
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": ["a@example.com", "b@example.com"],
                },
            },
        }
        result = _resolve_recipients(plan_content)
        assert result == ["a@example.com", "b@example.com"]

    def test_falls_back_to_global_when_plan_has_no_recipients(self) -> None:
        plan_content = {"custom": {}}
        with patch("osint_core.config.settings") as mock_settings:
            mock_settings.resend_recipients = "global@example.com"
            result = _resolve_recipients(plan_content)
        assert result == ["global@example.com"]

    def test_falls_back_to_global_when_plan_content_is_none(self) -> None:
        with patch("osint_core.config.settings") as mock_settings:
            mock_settings.resend_recipients = "fallback@example.com"
            result = _resolve_recipients(None)
        assert result == ["fallback@example.com"]

    def test_falls_back_to_global_when_plan_recipients_empty(self) -> None:
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": [],
                },
            },
        }
        with patch("osint_core.config.settings") as mock_settings:
            mock_settings.resend_recipients = "fallback@example.com"
            result = _resolve_recipients(plan_content)
        assert result == ["fallback@example.com"]

    def test_strips_whitespace_from_plan_recipients(self) -> None:
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": ["  a@example.com  ", " b@example.com"],
                },
            },
        }
        result = _resolve_recipients(plan_content)
        assert result == ["a@example.com", "b@example.com"]

    def test_skips_empty_strings_in_plan_recipients(self) -> None:
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": ["a@example.com", "", "  "],
                },
            },
        }
        result = _resolve_recipients(plan_content)
        assert result == ["a@example.com"]

    def test_expands_env_var_placeholders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CAL_REPORT_RECIPIENT_1", "alice@example.com")
        monkeypatch.setenv("CAL_REPORT_RECIPIENT_2", "bob@example.com")
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": [
                        "${CAL_REPORT_RECIPIENT_1}",
                        "${CAL_REPORT_RECIPIENT_2}",
                    ],
                },
            },
        }
        result = _resolve_recipients(plan_content)
        assert result == ["alice@example.com", "bob@example.com"]

    def test_env_var_with_comma_separated_recipients(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RECIPIENTS", "a@example.com,b@example.com, c@example.com")
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": ["${RECIPIENTS}"],
                },
            },
        }
        result = _resolve_recipients(plan_content)
        assert result == ["a@example.com", "b@example.com", "c@example.com"]

    def test_unset_env_vars_fall_back_to_global(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CAL_REPORT_RECIPIENT_1", raising=False)
        monkeypatch.delenv("CAL_REPORT_RECIPIENT_2", raising=False)
        plan_content = {
            "custom": {
                "resend": {
                    "recipients": [
                        "${CAL_REPORT_RECIPIENT_1}",
                        "${CAL_REPORT_RECIPIENT_2}",
                    ],
                },
            },
        }
        with patch("osint_core.config.settings") as mock_settings:
            mock_settings.resend_recipients = "fallback@example.com"
            result = _resolve_recipients(plan_content)
        assert result == ["fallback@example.com"]

    def test_returns_empty_when_no_plan_and_no_global(self) -> None:
        with patch("osint_core.config.settings") as mock_settings:
            mock_settings.resend_recipients = ""
            result = _resolve_recipients(None)
        assert result == []


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


class TestReportMetricsEmission:
    """Tests that report pipeline emits Prometheus metrics at key points."""

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_skipped_report_increments_generation_total(
        self, mock_session: MagicMock,
    ) -> None:
        """When no leads exist, report_generation_total{outcome=skipped} increments."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        before = metrics.report_generation_total.labels(outcome="skipped")._value.get()

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(return_value=None)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            await _generate_report_async()

        after = metrics.report_generation_total.labels(outcome="skipped")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_successful_report_emits_duration_and_generation_total(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """A successful report observes duration and increments completed counter."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        before_count = metrics.report_generation_total.labels(
            outcome="completed",
        )._value.get()
        before_sum = metrics.report_generation_duration_seconds._sum.get()

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        after_count = metrics.report_generation_total.labels(
            outcome="completed",
        )._value.get()
        after_sum = metrics.report_generation_duration_seconds._sum.get()

        assert after_count == before_count + 1
        assert after_sum > before_sum

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_successful_email_increments_sent_counter(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """A successful email send increments report_email_total{outcome=sent}."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        before = metrics.report_email_total.labels(outcome="sent")._value.get()

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        after = metrics.report_email_total.labels(outcome="sent")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.asyncio.sleep", new_callable=AsyncMock)
    @patch("osint_core.workers.prospecting.async_session")
    async def test_failed_email_increments_failed_counter(
        self,
        mock_session: MagicMock,
        mock_sleep: AsyncMock,
        mock_report_result: MagicMock,
    ) -> None:
        """All email retries exhausted increments report_email_total{outcome=failed}."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        before = metrics.report_email_total.labels(outcome="failed")._value.get()

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=False)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        after = metrics.report_email_total.labels(outcome="failed")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_report_leads_total_set_on_success(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Lead count gauges are set when report generates successfully."""
        mock_db = AsyncMock()
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        # Set lead_count to a known value on the mock result
        mock_report_result.lead_count = 5

        with (
            patch(
                "osint_core.services.prospecting_report.ProspectingReportGenerator",
                autospec=True,
            ) as mock_gen_cls,
            patch(
                "osint_core.services.resend_notifier.ResendNotifier",
                autospec=True,
            ) as mock_notifier_cls,
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        rendered = metrics.report_leads_total.labels(stage="rendered")._value.get()
        assert rendered == 5


class TestEmailDeliveryLogging:
    """Tests for structured email delivery logging."""

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.asyncio.sleep", new_callable=AsyncMock)
    @patch("osint_core.workers.prospecting.async_session")
    async def test_email_delivery_log_includes_structured_fields(
        self,
        mock_session: MagicMock,
        mock_sleep: AsyncMock,
        mock_report_result: MagicMock,
    ) -> None:
        """Email delivery completion log includes artifact_uri, recipient_count, latency_ms."""
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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
            patch("osint_core.workers.prospecting.logger") as mock_logger,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "a@example.com,b@example.com"

            await _generate_report_async()

        # Find the report_email_delivered log call
        delivery_calls = [
            c for c in mock_logger.info.call_args_list
            if "report_email_delivered" in str(c)
        ]
        assert len(delivery_calls) == 1
        call_str = str(delivery_calls[0])
        assert "artifact_uri" in call_str
        assert mock_report_result.artifact_uri in call_str
        assert "recipient_count" in call_str
        assert "latency_ms" in call_str


class TestReportDateForwarding:
    """Tests that report_date from ReportResult is forwarded to the notifier."""

    @pytest.mark.asyncio()
    @patch("osint_core.workers.prospecting.async_session")
    async def test_send_report_receives_report_date(
        self,
        mock_session: MagicMock,
        mock_report_result: MagicMock,
    ) -> None:
        """notifier.send_report() receives report_date=result.report_date."""
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
            patch(
                "osint_core.services.plan_store.PlanStore",
                autospec=True,
            ) as mock_store_cls,
            patch("osint_core.config.settings") as mock_settings,
        ):
            mock_gen_cls.return_value.generate_report = AsyncMock(
                return_value=mock_report_result,
            )
            mock_notifier_cls.return_value.send_report = AsyncMock(return_value=True)
            mock_store_cls.return_value.get_active = AsyncMock(return_value=None)
            mock_settings.resend_recipients = "test@example.com"

            await _generate_report_async()

        call_kwargs = mock_notifier_cls.return_value.send_report.call_args
        assert call_kwargs.kwargs["report_date"] == mock_report_result.report_date


class TestGenerationFailureMetrics:
    """Tests that generation failure emits the correct Prometheus metric."""

    @patch("osint_core.workers.prospecting._check_pipeline_guard")
    def test_generation_failure_increments_failed_counter(
        self,
        mock_guard: MagicMock,
    ) -> None:
        """report_generation_total{outcome=failed} increments when generation
        raises an exception and retries are exhausted."""
        from celery.exceptions import Retry

        from osint_core.workers.prospecting import generate_prospecting_report_task

        mock_guard.return_value = MagicMock(
            should_defer=False, deferrals=0,
        )

        before = metrics.report_generation_total.labels(outcome="failed")._value.get()

        with (
            patch(
                "osint_core.workers.prospecting.asyncio.new_event_loop",
            ) as mock_loop_factory,
            patch.object(
                generate_prospecting_report_task, "retry", side_effect=Retry(),
            ),
        ):
            loop = MagicMock()
            loop.run_until_complete.side_effect = RuntimeError("generation boom")
            mock_loop_factory.return_value = loop

            # Push a fake request context with retries=3 so retries_used >= 3
            generate_prospecting_report_task.push_request(retries=3)
            try:
                with pytest.raises(Retry):
                    generate_prospecting_report_task()
            finally:
                generate_prospecting_report_task.pop_request()

        after = metrics.report_generation_total.labels(outcome="failed")._value.get()
        assert after == before + 1
