"""Tests for the ProspectingReportGenerator service."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.courtlistener import VerifiedCitation
from osint_core.services.prospecting_report import (
    ProspectingReportGenerator,
    _archive_pdf,
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
    db.add = MagicMock()  # session.add() is synchronous

    async def _flush_side_effect() -> None:
        """Simulate DB flush populating server-side defaults (e.g. UUIDMixin.id)."""
        for call in db.add.call_args_list:
            obj = call.args[0]
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    db.flush = AsyncMock(side_effect=_flush_side_effect)
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

    def test_query_includes_severity_confidence_ordering(self):
        """The reportable-leads query orders by severity CASE then confidence DESC."""
        from sqlalchemy import case, or_, select

        from osint_core.models.lead import Lead

        severity_order = case(
            (Lead.severity == "critical", 0),
            (Lead.severity == "high", 1),
            (Lead.severity == "medium", 2),
            (Lead.severity == "low", 3),
            else_=4,
        )
        stmt = (
            select(Lead)
            .where(
                Lead.plan_id == "cal-prospecting",
                or_(
                    Lead.status == "new",
                    (Lead.status == "reviewing")
                    & (Lead.last_updated_at > Lead.reported_at),
                ),
            )
            .order_by(severity_order, Lead.confidence.desc())
        )
        compiled = str(stmt)
        assert "ORDER BY" in compiled
        assert "CASE" in compiled
        assert "DESC" in compiled
        # Verify severity ordering: critical < high < medium < low
        crit_pos = compiled.index("severity_1")
        high_pos = compiled.index("severity_2")
        med_pos = compiled.index("severity_3")
        low_pos = compiled.index("severity_4")
        assert crit_pos < high_pos < med_pos < low_pos


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
    async def test_leads_appear_in_severity_confidence_order(self, generator):
        """Leads passed to the template follow severity/confidence ordering."""
        lead_low = _make_lead(severity="low", title="Low-Sev")
        lead_low.confidence = 0.9
        lead_critical = _make_lead(severity="critical", title="Critical-Sev")
        lead_critical.confidence = 0.8
        lead_high_a = _make_lead(severity="high", title="High-Sev-LowConf")
        lead_high_a.confidence = 0.6
        lead_high_b = _make_lead(severity="high", title="High-Sev-HighConf")
        lead_high_b.confidence = 0.95

        # DB returns them in severity/confidence order (as the ORDER BY would)
        ordered = [lead_critical, lead_high_b, lead_high_a, lead_low]
        db = _mock_db(ordered)

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
        titles = [ld["title"] for ld in ctx["leads"]]
        assert titles == [
            "Critical-Sev",
            "High-Sev-HighConf",
            "High-Sev-LowConf",
            "Low-Sev",
        ]

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


    @pytest.mark.asyncio()
    async def test_creates_report_record_with_correct_artifact_uri(self, generator):
        """generate_report creates a Report record with the correct artifact_uri."""
        leads = [_make_lead()]
        db = _mock_db(leads)

        with patch(f"{_MOD}.httpx.AsyncClient") as mock_cls, \
             patch(f"{_MOD}._archive_pdf", return_value="minio://bucket/report.pdf"), \
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

        # Verify db.add was called with a Report instance (check call_args_list
        # for resilience if additional objects are ever added in the future)
        report_adds = [
            call.args[0]
            for call in db.add.call_args_list
            if type(call.args[0]).__name__ == "Report"
        ]
        assert len(report_adds) == 1, "Expected exactly one Report to be added"
        report = report_adds[0]
        assert report.artifact_uri == "minio://bucket/report.pdf"
        assert report.lead_count == 1
        assert report.plan_id == "cal-prospecting"

    @pytest.mark.asyncio()
    async def test_leads_have_report_id_set(self, generator):
        """Leads included in the report have report_id set to the Report's ID."""
        lead1 = _make_lead(status="new")
        lead2 = _make_lead(status="new", lead_type="policy")
        db = _mock_db([lead1, lead2])

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

        # Both leads should have report_id set to the same Report ID
        report_adds = [
            call.args[0]
            for call in db.add.call_args_list
            if type(call.args[0]).__name__ == "Report"
        ]
        assert len(report_adds) == 1
        report = report_adds[0]
        assert lead1.report_id == report.id
        assert lead2.report_id == report.id
        assert lead1.report_id is not None


class TestArchivePdf:
    """Tests for the _archive_pdf helper."""

    @pytest.mark.asyncio()
    async def test_passes_evidentiary_retention_class(self):
        """_archive_pdf uploads with retention_class='evidentiary'."""
        mock_upload = MagicMock(return_value="minio://osint-reports/prospecting/test.pdf")

        with patch(f"{_MOD}.upload_pdf_to_minio", mock_upload):
            uri = await _archive_pdf(b"%PDF-data", datetime.now(UTC))

        assert uri == "minio://osint-reports/prospecting/test.pdf"
        mock_upload.assert_called_once()
        call_kwargs = mock_upload.call_args
        assert call_kwargs.kwargs.get("retention_class") == "evidentiary"
