"""Tests for the ProspectingReportGenerator service."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.courtlistener import VerifiedCitation
from osint_core.services.prospecting_report import (
    ProspectingReportGenerator,
    _fallback_narrative,
    _select_reportable_leads,
)

_MOD = "osint_core.services.prospecting_report"


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

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://test"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):
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

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):
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
    async def test_archive_failure_raises(self, generator):
        db = _mock_db([_make_lead()])

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value=""), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="PDF archival"):
                await generator.generate_report(db)

    @pytest.mark.asyncio()
    async def test_fallback_on_vllm_failure(self, generator):
        leads = [_make_lead()]
        db = _mock_db(leads)

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("vLLM down"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1

    @pytest.mark.asyncio()
    async def test_courtlistener_citations_included_in_report(self):
        leads = [_make_lead()]
        db = _mock_db(leads)

        mock_citations = [
            VerifiedCitation(
                case_name="Tinker v. Des Moines",
                citation="393 U.S. 503",
                courtlistener_url="https://www.courtlistener.com/opinion/123/",
                verified=True,
                relevance="matched",
                holding_summary="Students have free speech rights.",
            ),
            VerifiedCitation(
                case_name="Unknown v. State",
                citation="999 F.3d 1",
                courtlistener_url="",
                verified=False,
                relevance="not independently verified",
                holding_summary="",
            ),
        ]
        mock_cl = AsyncMock()
        mock_cl.api_key = "test-key"
        mock_cl.verify_citations = AsyncMock(return_value=mock_citations)
        generator = ProspectingReportGenerator(courtlistener=mock_cl)

        vllm_response = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "executive_summary": "Summary referencing Tinker v. Des Moines",
                        "constitutional_analysis": "Analysis",
                    }),
                },
            }],
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = vllm_response

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await generator.generate_report(db)

        assert result is not None
        # Verify CourtListener was called
        mock_cl.verify_citations.assert_called_once()
        # Verify legal citations passed to template context
        render_kwargs = mock_render.call_args
        ctx = render_kwargs.args[0] if render_kwargs.args else render_kwargs.kwargs
        legal_cites = ctx.get("all_legal_citations") or []
        assert len(legal_cites) == 2
        assert legal_cites[0]["verified"] is True
        assert legal_cites[1]["verified"] is False

    @pytest.mark.asyncio()
    async def test_report_succeeds_when_courtlistener_unavailable(self):
        leads = [_make_lead()]
        db = _mock_db(leads)

        mock_cl = AsyncMock()
        mock_cl.api_key = "test-key"
        mock_cl.verify_citations = AsyncMock(side_effect=Exception("API down"))
        generator = ProspectingReportGenerator(courtlistener=mock_cl)

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1

    @pytest.mark.asyncio()
    async def test_weasyprint_failure_raises_runtime_error(self, generator):
        """WeasyPrint rendering errors are caught, logged, and re-raised."""
        leads = [_make_lead()]
        db = _mock_db(leads)

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"), \
             patch("weasyprint.HTML") as mock_html:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            mock_html.return_value.write_pdf.side_effect = OSError(
                "cairo surface error"
            )

            with pytest.raises(RuntimeError, match="PDF rendering failed"):
                await generator.generate_report(db)

    @pytest.mark.asyncio()
    async def test_unverified_citations_flagged(self):
        leads = [_make_lead()]
        db = _mock_db(leads)

        mock_citations = [
            VerifiedCitation(
                case_name="Fake v. Case",
                citation="000 U.S. 000",
                courtlistener_url="",
                verified=False,
                relevance="not independently verified",
                holding_summary="",
            ),
        ]
        mock_cl = AsyncMock()
        mock_cl.api_key = "test-key"
        mock_cl.verify_citations = AsyncMock(return_value=mock_citations)
        generator = ProspectingReportGenerator(courtlistener=mock_cl)

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await generator.generate_report(db)

        render_kwargs = mock_render.call_args
        ctx = render_kwargs.args[0] if render_kwargs.args else render_kwargs.kwargs
        legal_cites = ctx.get("all_legal_citations") or []
        assert len(legal_cites) == 1
        assert legal_cites[0]["relevance"] == "not independently verified"
