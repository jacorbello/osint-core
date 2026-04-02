"""Integration tests for the deep analysis pipeline."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SAMPLE_PLAN_CONTENT = {
    "custom": {
        "deep_analysis_enabled": True,
        "deep_analysis_relevance_gate": False,
        "precedent_map": {
            "1A-free-speech": {
                "compelled_speech": [
                    {"case": "West Virginia v. Barnette", "citation": "319 U.S. 624 (1943)"},
                ],
            },
        },
    },
    "scoring": {"source_reputation": {}},
}

SAMPLE_SCREENING_RESULT = {
    "relevant": True,
    "language": "en",
    "lead_title": "Student Conduct Policy",
    "document_summary": "Student conduct policy with speech requirements.",
    "overall_assessment": "Contains one high-severity compelled speech provision.",
    "flagged_sections": ["§ 5.1 - Mandatory Training"],
}

SAMPLE_PROVISION_RESULT = {
    "section_reference": "§ 5.1",
    "quoted_language": "All students must attend mandatory training.",
    "constitutional_issue": "Compelled speech in mandatory training",
    "constitutional_basis": "1A-free-speech",
    "severity": "high",
    "affected_population": "All enrolled students",
    "facial_or_as_applied": "facial",
    "sources_cited": ["West Virginia v. Barnette"],
}


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_analyze_leads_produces_deep_analysis(self) -> None:
        """Verify the full pipeline: pending lead → deep analysis → completed."""
        from osint_core.workers.prospecting import _analyze_leads_async

        lead = MagicMock()
        lead.id = uuid.uuid4()
        lead.lead_type = "policy"
        lead.title = "Student Conduct Policy"
        lead.institution = "Test University"
        lead.jurisdiction = "TX"
        lead.constitutional_basis = ["1A-free-speech"]
        lead.severity = "medium"
        lead.confidence = 0.8
        lead.event_ids = [uuid.uuid4()]
        lead.plan_id = "cal-prospecting"
        lead.analysis_status = "pending"
        lead.deep_analysis = None

        event = MagicMock()
        event.id = lead.event_ids[0]
        event.metadata_ = {
            "minio_uri": "minio://osint-artifacts/test.html",
            "document_type": "html",
        }
        event.nlp_relevance = "relevant"

        plan_version = MagicMock()
        plan_version.plan_id = "cal-prospecting"
        plan_version.content = SAMPLE_PLAN_CONTENT
        plan_version.is_active = True

        db = AsyncMock()
        # Call 1: select plan version
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan_version
        # Call 2: select pending leads
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = [lead]
        # Call 3: select event
        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event

        db.execute = AsyncMock(side_effect=[plan_result, lead_result, event_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        # Document must be long enough to pass check_content gate (100 chars)
        doc_bytes = (
            b"<p>Student conduct policy with mandatory"
            b" training requirements for all students.</p>"
        ) * 5

        # Two-pass: first call is screening, second is provision analysis
        llm_responses = [
            json.dumps(SAMPLE_SCREENING_RESULT),
            json.dumps(SAMPLE_PROVISION_RESULT),
        ]

        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch(
                "osint_core.services.deep_analyzer.DeepAnalyzer._retrieve_document",
                new_callable=AsyncMock,
                return_value=doc_bytes,
            ),
            patch(
                "osint_core.services.deep_analyzer.llm_chat_completion",
                new_callable=AsyncMock,
                side_effect=llm_responses,
            ),
            patch(
                "osint_core.services.deep_analyzer.CourtListenerClient.lookup_precedent",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "completed"
        assert result["analyzed"] == 1
        assert lead.analysis_status == "completed"
        assert lead.deep_analysis["actionable"] is True
        assert len(lead.deep_analysis["provisions"]) == 1
        assert lead.deep_analysis["provisions"][0]["section_reference"] == "§ 5.1"
