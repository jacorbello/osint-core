"""Tests for DeepAnalyzer service."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.deep_analyzer import DeepAnalyzer, _POLICY_ANALYSIS_SCHEMA, _INCIDENT_ANALYSIS_SCHEMA


def _make_lead(*, lead_type: str = "policy", event_ids: list | None = None) -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = lead_type
    lead.title = "Test Policy"
    lead.summary = "A university policy about speech."
    lead.institution = "UC Berkeley"
    lead.jurisdiction = "CA"
    lead.constitutional_basis = ["1A-free-speech"]
    lead.severity = "medium"
    lead.confidence = 0.8
    lead.event_ids = event_ids or [uuid.uuid4()]
    lead.plan_id = "cal-prospecting"
    lead.deep_analysis = None
    lead.analysis_status = "pending"
    return lead


def _make_event(*, minio_uri: str | None = "minio://osint-artifacts/policy.html") -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.metadata_ = {"minio_uri": minio_uri, "document_type": "html"} if minio_uri else {}
    event.raw_excerpt = "https://example.edu/policy"
    event.title = "Test Policy"
    return event


SAMPLE_POLICY_ANALYSIS = {
    "provisions": [
        {
            "section_reference": "§ 4.2",
            "quoted_language": "Students must use preferred pronouns.",
            "constitutional_issue": "Compelled speech",
            "constitutional_basis": "1A-free-speech",
            "severity": "high",
            "affected_population": "All students",
            "facial_or_as_applied": "facial",
        }
    ],
    "document_summary": "Policy regulating campus speech.",
    "overall_assessment": "Contains one actionable provision.",
    "actionable": True,
}

SAMPLE_INCIDENT_ANALYSIS = {
    "incident_summary": "Professor terminated for classroom speech.",
    "rights_violated": ["1A-free-speech"],
    "individuals_identified": [{"name": "Dr. Smith", "role": "faculty"}],
    "institution": "UC Berkeley",
    "corroboration_strength": "strong",
    "corroboration_notes": "Confirmed by multiple news sources.",
    "actionable": True,
}


class TestAnalyzePolicy:
    @pytest.mark.asyncio
    async def test_analyzes_policy_document(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        with (
            patch.object(analyzer, "_retrieve_document", new_callable=AsyncMock, return_value=b"<p>Policy text</p>"),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(SAMPLE_POLICY_ANALYSIS)),
            patch.object(analyzer, "_attach_precedent", new_callable=AsyncMock, return_value=SAMPLE_POLICY_ANALYSIS),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is True
        assert len(result["provisions"]) == 1
        assert result["provisions"][0]["section_reference"] == "§ 4.2"

    @pytest.mark.asyncio
    async def test_non_actionable_policy(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        empty_result = {
            "provisions": [],
            "document_summary": "Administrative policy.",
            "overall_assessment": "No constitutional issues.",
            "actionable": False,
        }

        with (
            patch.object(analyzer, "_retrieve_document", new_callable=AsyncMock, return_value=b"<p>Admin stuff</p>"),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(empty_result)),
            patch.object(analyzer, "_attach_precedent", new_callable=AsyncMock, return_value=empty_result),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is False
        assert result["provisions"] == []


class TestAnalyzeIncident:
    @pytest.mark.asyncio
    async def test_analyzes_incident(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="incident")
        event = _make_event(minio_uri=None)
        event.raw_excerpt = "https://example.com/article"

        with (
            patch.object(analyzer, "_fetch_article_content", new_callable=AsyncMock, return_value="Article about professor firing."),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(SAMPLE_INCIDENT_ANALYSIS)),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is True
        assert result["corroboration_strength"] == "strong"


class TestNoSourceMaterial:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_document(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event(minio_uri=None)
        event.raw_excerpt = None

        result = await analyzer.analyze_lead(lead, event)
        assert result is None
