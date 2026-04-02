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
    _extract_json,
    _fallback_narrative,
    _filter_reportable_leads,
    _group_skipped_leads,
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
    analysis_status: str = "pending",
    deep_analysis: dict | None = None,
    citations: dict | None = None,
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
    lead.citations = citations if citations is not None else {"sources": ["https://example.com/article"]}
    lead.reported_at = reported_at
    lead.last_updated_at = last_updated_at or datetime.now(UTC)
    lead.analysis_status = analysis_status
    lead.deep_analysis = deep_analysis
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

        narrative = json.dumps({
            "executive_summary": "Summary",
            "constitutional_analysis": "Analysis",
            "recommendation": "Recommend",
        })

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value=narrative), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://test"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

            await generator.generate_report(db)

        assert lead_new.status == "reviewing"
        assert lead_new.reported_at is not None
        db.commit.assert_called_once()

    @pytest.mark.asyncio()
    async def test_archive_failure_raises(self, generator):
        db = _mock_db([_make_lead()])

        with (
            patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"),
            patch(f"{_MOD}._archive_pdf", return_value=""),
            patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"),
            pytest.raises(RuntimeError, match="PDF archival"),
        ):
            await generator.generate_report(db)

    @pytest.mark.asyncio()
    async def test_fallback_on_llm_failure(self, generator):
        leads = [_make_lead()]
        db = _mock_db(leads)

        mock_llm = AsyncMock(side_effect=Exception("LLM down"))
        with patch(f"{_MOD}.llm_chat_completion", mock_llm), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1

    @pytest.mark.asyncio()
    async def test_fallback_on_unparseable_content(self, generator):
        """When LLM returns non-JSON content, fallback is used."""
        leads = [_make_lead()]
        db = _mock_db(leads)

        mock_llm = AsyncMock(return_value="Not valid JSON at all")
        with patch(f"{_MOD}.llm_chat_completion", mock_llm), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1

    @pytest.mark.asyncio()
    async def test_llm_called_with_expected_params(self, generator):
        """The llm_chat_completion call includes expected parameters."""
        leads = [_make_lead()]
        db = _mock_db(leads)
        narrative = json.dumps({
            "executive_summary": "Test",
            "constitutional_analysis": "Test",
            "recommendation": "Test",
        })

        mock_llm = AsyncMock(return_value=narrative)
        with patch(f"{_MOD}.llm_chat_completion", mock_llm), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

            await generator.generate_report(db)

        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1500
        assert call_kwargs["temperature"] == 0.2
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["json_schema"] is not None

    @pytest.mark.asyncio()
    async def test_parses_markdown_fenced_json(self, generator):
        """LLM output wrapped in markdown fences is parsed (#211)."""
        leads = [_make_lead()]
        db = _mock_db(leads)
        narrative_dict = {
            "executive_summary": "Fenced test",
            "constitutional_analysis": "Analysis",
            "recommendation": "Rec",
        }
        fenced = f"```json\n{json.dumps(narrative_dict)}\n```"

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value=fenced), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:

            result = await generator.generate_report(db)

        assert result is not None
        # _render_pdf_html is called with a single dict arg
        ctx = mock_render.call_args[0][0]
        sections = ctx["leads"][0]["sections"]
        assert sections["executive_summary"] == "Fenced test"

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:

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

        narrative = json.dumps({
            "executive_summary": "Summary referencing Tinker v. Des Moines",
            "constitutional_analysis": "Analysis",
        })

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value=narrative), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

            result = await generator.generate_report(db)

        assert result is not None
        assert result.lead_count == 1

    @pytest.mark.asyncio()
    async def test_weasyprint_failure_raises_runtime_error(self, generator):
        """WeasyPrint rendering errors are caught, logged, and re-raised."""
        leads = [_make_lead()]
        db = _mock_db(leads)

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"), \
             patch("weasyprint.HTML") as mock_html:

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>") as mock_render:

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://bucket/report.pdf"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

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

        with patch(f"{_MOD}.llm_chat_completion", new_callable=AsyncMock, return_value="{}"), \
             patch(f"{_MOD}._archive_pdf", return_value="minio://ok"), \
             patch(f"{_MOD}._render_pdf_html", return_value="<html></html>"):

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


class TestExtractJson:
    """Tests for _extract_json (#211)."""

    _VALID = {
        "executive_summary": "Free speech violation at UC Berkeley.",
        "constitutional_analysis": "First Amendment issue.",
        "recommendation": "Investigate further.",
    }

    def test_parses_raw_json(self):
        assert _extract_json(json.dumps(self._VALID)) == self._VALID

    def test_strips_markdown_fence(self):
        content = f"```json\n{json.dumps(self._VALID)}\n```"
        assert _extract_json(content) == self._VALID

    def test_strips_fence_without_lang(self):
        content = f"```\n{json.dumps(self._VALID)}\n```"
        assert _extract_json(content) == self._VALID

    def test_extracts_json_from_prose(self):
        content = (
            "Here is the analysis:\n\n"
            f"{json.dumps(self._VALID)}\n\n"
            "Let me know if you need more detail."
        )
        assert _extract_json(content) == self._VALID

    def test_returns_none_for_empty(self):
        assert _extract_json("") is None
        assert _extract_json("   ") is None

    def test_returns_none_for_plain_text(self):
        assert _extract_json("No JSON here at all.") is None

    def test_returns_none_for_array(self):
        assert _extract_json('[1, 2, 3]') is None

    def test_handles_nested_braces(self):
        data = {"summary": "test {nested} braces", "key": "value"}
        assert _extract_json(json.dumps(data)) == data

    def test_multiple_json_blocks_returns_first_valid(self):
        """When prose contains multiple brace blocks, the first valid dict wins."""
        content = (
            'Some text with {invalid json} in the middle.\n'
            f'Then the real payload: {json.dumps(self._VALID)}\n'
            'And more text.'
        )
        assert _extract_json(content) == self._VALID

    def test_skips_non_dict_brace_block(self):
        """Brace blocks that aren't dicts are skipped."""
        content = (
            'Not JSON: {just some braces}\n'
            f'{json.dumps(self._VALID)}'
        )
        assert _extract_json(content) == self._VALID


class TestReportFiltering:
    """Tests for _filter_reportable_leads and _group_skipped_leads."""

    def test_non_actionable_leads_excluded(self):
        """Lead with analysis_status='not_actionable' should be filtered out."""
        lead = _make_lead(analysis_status="not_actionable")
        result = _filter_reportable_leads([lead])
        assert result == []

    def test_completed_leads_included(self):
        """Lead with analysis_status='completed' should pass through."""
        lead = _make_lead(analysis_status="completed")
        result = _filter_reportable_leads([lead])
        assert len(result) == 1
        assert result[0] is lead

    def test_pending_leads_included(self):
        """Lead with analysis_status='pending' should pass through."""
        lead = _make_lead(analysis_status="pending")
        result = _filter_reportable_leads([lead])
        assert len(result) == 1

    def test_extraction_failed_excluded(self):
        """Lead with analysis_status='extraction_failed' should be filtered out."""
        lead = _make_lead(analysis_status="extraction_failed")
        result = _filter_reportable_leads([lead])
        assert result == []

    def test_non_english_excluded(self):
        """Lead with analysis_status='non_english' should be filtered out."""
        lead = _make_lead(analysis_status="non_english")
        result = _filter_reportable_leads([lead])
        assert result == []

    def test_no_content_excluded(self):
        """Lead with analysis_status='no_content' should be filtered out."""
        lead = _make_lead(analysis_status="no_content")
        result = _filter_reportable_leads([lead])
        assert result == []

    def test_failed_excluded(self):
        """Lead with analysis_status='failed' should be filtered out."""
        lead = _make_lead(analysis_status="failed")
        result = _filter_reportable_leads([lead])
        assert result == []

    def test_mixed_leads_filtered_correctly(self):
        """Mix of statuses: only reportable leads pass through."""
        leads = [
            _make_lead(analysis_status="completed", title="Good"),
            _make_lead(analysis_status="not_actionable", title="Bad"),
            _make_lead(analysis_status="extraction_failed", title="Skip"),
            _make_lead(analysis_status="pending", title="Pending"),
        ]
        result = _filter_reportable_leads(leads)
        titles = [lead.title for lead in result]
        assert titles == ["Good", "Pending"]

    def test_skipped_leads_grouped_by_status(self):
        """Leads with skipped statuses are grouped correctly."""
        lead_a = _make_lead(analysis_status="extraction_failed", title="Doc A")
        lead_a.institution = "UC Davis"
        lead_b = _make_lead(analysis_status="non_english", title="Doc B")
        lead_b.institution = "UCLA"
        lead_c = _make_lead(analysis_status="no_content", title="Doc C")
        lead_c.institution = "UCSF"
        lead_d = _make_lead(analysis_status="extraction_failed", title="Doc D")
        lead_d.institution = "UCSD"
        leads = [
            lead_a, lead_b, lead_c, lead_d,
            _make_lead(analysis_status="completed", title="Good One"),
            _make_lead(analysis_status="pending", title="Pending One"),
        ]
        result = _group_skipped_leads(leads)

        assert "extraction_failed" in result
        assert len(result["extraction_failed"]) == 2
        assert result["extraction_failed"][0]["title"] == "Doc A"
        assert result["extraction_failed"][1]["title"] == "Doc D"

        assert "non_english" in result
        assert len(result["non_english"]) == 1
        assert result["non_english"][0]["institution"] == "UCLA"

        assert "no_content" in result
        assert len(result["no_content"]) == 1

        # completed and pending should NOT be grouped
        assert "completed" not in result
        assert "pending" not in result

    def test_skipped_leads_extract_source_url(self):
        """Skipped lead entries include source_url from citations."""
        lead = _make_lead(
            analysis_status="extraction_failed",
            citations={
                "source_citations": [{"url": "https://example.com/policy.pdf"}],
            },
        )
        result = _group_skipped_leads([lead])
        assert result["extraction_failed"][0]["source_url"] == "https://example.com/policy.pdf"

    def test_skipped_leads_empty_source_url_when_no_citations(self):
        """Skipped lead entries have empty source_url when no citations available."""
        lead = _make_lead(analysis_status="no_content", citations=None)
        result = _group_skipped_leads([lead])
        assert result["no_content"][0]["source_url"] == ""
