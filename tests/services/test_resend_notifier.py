"""Tests for the ResendNotifier service."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.services.resend_notifier import (
    ResendNotifier,
    _build_html_body,
    _validate_recipients,
)


class TestBuildHtmlBody:
    def test_includes_summary(self):
        html = _build_html_body("3 new leads found")
        assert "3 new leads found" in html
        assert "Executive Summary" in html

    def test_includes_branding(self):
        html = _build_html_body("test")
        assert "libertycenter.org" in html
        assert "CAL Prospecting Report" in html


class TestResendNotifier:
    @pytest.fixture()
    def notifier(self):
        return ResendNotifier(api_key="re_test_key", from_email="test@example.com")

    @pytest.mark.asyncio()
    async def test_no_api_key_returns_false(self):
        notifier = ResendNotifier(api_key="", from_email="test@example.com")
        result = await notifier.send_report(b"pdf", "summary", ["a@b.com"])
        assert result is False

    @pytest.mark.asyncio()
    async def test_no_recipients_returns_false(self, notifier):
        result = await notifier.send_report(b"pdf", "summary", [])
        assert result is False

    @pytest.mark.asyncio()
    async def test_successful_send(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await notifier.send_report(
                b"%PDF-1.4 test", "3 leads found", ["lawyer@cal.org"],
            )

        assert result is True

    @pytest.mark.asyncio()
    async def test_sends_correct_payload(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await notifier.send_report(
                b"pdf-data", "summary text", ["a@b.com", "c@d.com"],
            )

        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["from"] == "test@example.com"
        assert payload["to"] == ["a@b.com", "c@d.com"]
        assert "CAL Prospecting Report" in payload["subject"]
        assert len(payload["attachments"]) == 1
        assert payload["attachments"][0]["type"] == "application/pdf"

    @pytest.mark.asyncio()
    async def test_sends_auth_header(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await notifier.send_report(b"pdf", "summary", ["a@b.com"])

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer re_test_key"

    @pytest.mark.asyncio()
    async def test_timeout_returns_false(self, notifier):
        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await notifier.send_report(b"pdf", "summary", ["a@b.com"])

        assert result is False

    @pytest.mark.asyncio()
    async def test_http_error_returns_false(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Invalid email"
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "error", request=MagicMock(), response=mock_resp,
            ),
        )

        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await notifier.send_report(b"pdf", "summary", ["a@b.com"])

        assert result is False

    @pytest.mark.asyncio()
    async def test_pdf_attachment_is_base64_encoded(self, notifier):
        import base64

        pdf_data = b"%PDF-1.4 test content"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await notifier.send_report(pdf_data, "summary", ["a@b.com"])

        payload = mock_client.post.call_args.kwargs["json"]
        encoded = payload["attachments"][0]["content"]
        assert base64.b64decode(encoded) == pdf_data

    @pytest.mark.asyncio()
    async def test_invalid_emails_filtered_out(self, notifier):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with (
            patch("osint_core.services.resend_notifier.httpx.AsyncClient") as mock_cls,
            patch("osint_core.services.resend_notifier.logger") as mock_logger,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await notifier.send_report(
                b"pdf", "summary", ["valid@example.com", "not-an-email", "also@valid.org"],
            )

        assert result is True
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["to"] == ["valid@example.com", "also@valid.org"]
        mock_logger.warning.assert_any_call("resend_invalid_email", email="not-an-email")

    @pytest.mark.asyncio()
    async def test_all_invalid_emails_returns_false(self, notifier):
        with patch("osint_core.services.resend_notifier.logger") as mock_logger:
            result = await notifier.send_report(
                b"pdf", "summary", ["bad-email", "@nope", "missing-domain@"],
            )

        assert result is False
        mock_logger.warning.assert_any_call("resend_invalid_email", email="bad-email")
        mock_logger.warning.assert_any_call("resend_invalid_email", email="@nope")
        mock_logger.warning.assert_any_call("resend_invalid_email", email="missing-domain@")
        mock_logger.warning.assert_any_call("resend_no_valid_recipients")


class TestValidateRecipients:
    def test_valid_emails_pass(self):
        emails = ["user@example.com", "a.b+tag@domain.co"]
        assert _validate_recipients(emails) == emails

    def test_invalid_emails_filtered(self):
        emails = ["good@example.com", "bad", "@nope.com", "no-domain@"]
        with patch("osint_core.services.resend_notifier.logger") as mock_logger:
            result = _validate_recipients(emails)

        assert result == ["good@example.com"]
        mock_logger.warning.assert_any_call("resend_invalid_email", email="bad")
        mock_logger.warning.assert_any_call("resend_invalid_email", email="@nope.com")
        mock_logger.warning.assert_any_call("resend_invalid_email", email="no-domain@")
        assert mock_logger.warning.call_count == 3

    def test_empty_list(self):
        assert _validate_recipients([]) == []
