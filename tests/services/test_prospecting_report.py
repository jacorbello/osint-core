"""Tests for the ProspectingReportGenerator service."""

import json
import sys
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock weasyprint before importing the module under test
if "weasyprint" not in sys.modules:
    _mock_wp = MagicMock()
    _mock_html = MagicMock()
    _mock_html.write_pdf.return_value = b"%PDF-1.4 mock"
    _mock_wp.HTML.return_value = _mock_html
    sys.modules["weasyprint"] = _mock_wp

from osint_core.services.prospecting_report import (
    ProspectingReportGenerator,
    _fallback_narrative,
    _select_reportable_leads,
)


def _make_lead(
    *,
    lead_type: str = "incident",
    status: str = "new",
    title: str = "Test Lead",
    severity: str = "high",
    reported_at: datetime | None = None,
    last_updated_at: datetime | None = None,
) -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = lead_type
    lead.status = status
    lead.title = title
    lead.summary = "Test summary"
    lead.constitutional_basis = ["1A-free-speech"]
    lead.jurisdiction = "CA"
    lead.institution = "UC Berkeley"
    lead.severity = severity
    lead.confidence = 0.85
    lead.plan_id = "cal-prospecting"
    lead.event_ids = [uuid.uuid4()]
    lead.citations = {"sources": ["https://example.com/article"]}
    lead.reported_at = reported_at
    lead.last_updated_at = last_updated_at or datetime.now(UTC)
    return lead


def _mock_db(leads: list) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = leads
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


class TestSelectReportableLeads:
    @pytest.mark.asyncio()
    async def test_returns_leads_from_query(self):
        leads = [_make_lead(), _make_lead(status="reviewing")]
        db = _mock_db(leads)
        result = await _select_reportable_leads(db)
        assert len(result) == 2
        db.execute.assert_called_once()

    @pytest.mark.asyncio()
    async def test_returns_empty_when_no_leads(self):
        db = _mock_db([])
        result = await _select_reportable_leads(db)
        assert result == []


class TestFallbackNarrative:
    def test_produces_minimal_narrative(self):
        lead = _make_lead()
        result = _fallback_narrative(lead)
        assert "executive_summary" in result
        assert "constitutional_analysis" in result
        assert "recommendation" in result

    def test_uses_title_when_no_summary(self):
        lead = _make_lead()
        lead.summary = None
        lead.title = "Important Lead"
        result = _fallback_narrative(lead)
        assert result["executive_summary"] == "Important Lead"


class TestProspectingReportGenerator:
    @pytest.fixture()
    def generator(self):
        return ProspectingReportGenerator()

    @pytest.mark.asyncio()
    async def test_returns_none_when_no_leads(self, generator):
        db = _mock_db([])
        result = await generator.generate_report(db)
        assert result is None

    @pytest.mark.asyncio()
    async def test_generates_report_with_leads(self, generator):
        leads = [_make_lead(), _make_lead(lead_type="policy")]
        db = _mock_db(leads)

        vllm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "executive_summary": "Summary",
                        "constitutional_analysis": "Analysis",
                        "recommendation": "Recommend",
                    }),
                },
            }],
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = vllm_response

        with patch("osint_core.services.prospecting_report.httpx.AsyncClient") as mock_cls, \
             patch("osint_core.services.prospecting_report._archive_pdf", return_value="minio://test"), \
             patch("osint_core.services.prospecting_report._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 2
        assert result.artifact_uri == "minio://test"
        assert result.pdf_bytes == b"%PDF-1.4 mock"

    @pytest.mark.asyncio()
    async def test_updates_lead_statuses(self, generator):
        lead_new = _make_lead(status="new")
        lead_reviewing = _make_lead(status="reviewing")
        db = _mock_db([lead_new, lead_reviewing])

        with patch("osint_core.services.prospecting_report.httpx.AsyncClient") as mock_cls, \
             patch("osint_core.services.prospecting_report._archive_pdf", return_value=""), \
             patch("osint_core.services.prospecting_report._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await generator.generate_report(db)

        assert lead_new.status == "reviewing"
        assert lead_new.reported_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio()
    async def test_fallback_on_vllm_failure(self, generator):
        leads = [_make_lead()]
        db = _mock_db(leads)

        with patch("osint_core.services.prospecting_report.httpx.AsyncClient") as mock_cls, \
             patch("osint_core.services.prospecting_report._archive_pdf", return_value=""), \
             patch("osint_core.services.prospecting_report._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("vLLM down"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1
