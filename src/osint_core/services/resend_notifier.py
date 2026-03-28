"""Resend email notifier — sends PDF reports via Resend API."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import structlog

from osint_core.config import settings

logger = structlog.get_logger()

_RESEND_API_URL = "https://api.resend.com/emails"
_DEFAULT_TIMEOUT = 30.0


class ResendNotifier:
    """Send prospecting reports via Resend email API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_email: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.resend_api_key
        self.from_email = from_email or settings.resend_from_email

    async def send_report(
        self,
        pdf_bytes: bytes,
        executive_summary: str,
        recipients: list[str],
    ) -> bool:
        """Send a PDF report via Resend.

        Returns True on success, False on failure (logged but never raises).
        """
        if not self.api_key:
            logger.warning("resend_no_api_key")
            return False

        if not recipients:
            logger.warning("resend_no_recipients")
            return False

        now = datetime.now(UTC)
        subject = (
            f"CAL Prospecting Report — {now.strftime('%B %d, %Y %I:%M %p')} CST"
        )

        html_body = _build_html_body(executive_summary)

        payload = {
            "from": self.from_email,
            "to": recipients,
            "subject": subject,
            "html": html_body,
            "attachments": [
                {
                    "filename": f"cal-report-{now.strftime('%Y%m%d-%H%M')}.pdf",
                    "content": base64.b64encode(pdf_bytes).decode(),
                    "type": "application/pdf",
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    _RESEND_API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("resend_timeout", recipients=recipients)
            return False
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "resend_http_error",
                status=exc.response.status_code,
                detail=exc.response.text[:200],
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning("resend_error", error=str(exc))
            return False

        logger.info(
            "resend_sent",
            recipients=recipients,
            subject=subject,
        )
        return True


def _build_html_body(executive_summary: str) -> str:
    """Build a simple HTML email body with the executive summary."""
    return f"""\
<html>
<body style="font-family: Georgia, serif; color: #1a1a1a; max-width: 600px;">
<h2 style="color: #0d1b2a; border-bottom: 2px solid #c0392b; padding-bottom: 8px;">
    CAL Prospecting Report
</h2>
<p>Please find the attached prospecting report from
The Center For American Liberty.</p>
<h3 style="color: #1b3a5c;">Executive Summary</h3>
<div style="background: #f0f4f8; padding: 16px; border-left: 4px solid #1b3a5c;">
{executive_summary}
</div>
<hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
<p style="font-size: 11px; color: #888;">
    This report is confidential and intended for authorized recipients only.
    <br>The Center For American Liberty — libertycenter.org
</p>
</body>
</html>"""
