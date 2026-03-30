"""End-to-end integration test for the CAL prospecting pipeline.

Exercises the main chain: NLP enrichment (CAL mode) -> lead matching ->
report generation (HTML/template rendering) -> email notification.

External services used by the pipeline (LLM for enrichment, email delivery)
are mocked, but all internal logic (validation, fingerprinting, confidence
scoring, and HTML report rendering) runs for real. This test does not
exercise CourtListener/MinIO integrations or real PDF rendering.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest

from osint_core.services.lead_matcher import (
    LeadMatcher,
    LeadMatcherConfig,
    _entity_completeness,
    compute_confidence,
)
from osint_core.services.resend_notifier import ResendNotifier
from osint_core.workers.nlp_enrich import _validate_constitutional_fields
from osint_core.workers.prospecting import _build_matcher_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAL_PLAN_ID = "cal-prospecting"

_PLAN_CONTENT = {
    "enrichment": {"nlp_enabled": True, "mission": "Monitor constitutional rights."},
    "keywords": ["free speech", "first amendment", "due process"],
    "scoring": {"source_reputation": {"rss_fire": 0.9, "x_cal_california": 1.2}},
    "custom": {"lead_confidence_threshold": 0.3},
}


def _make_vllm_cal_response(
    *,
    summary: str = "Professor terminated after expressing political views in class.",
    relevance: str = "relevant",
    constitutional_basis: list[str] | None = None,
    lead_type: str = "incident",
    institution: str = "UC Berkeley",
    jurisdiction: str = "CA",
) -> dict:
    """Build a realistic vLLM JSON response for CAL enrichment."""
    return {
        "summary": summary,
        "relevance": relevance,
        "entities": [
            {"name": "Dr. Smith", "type": "affected_individual"},
            {"name": "UC Berkeley", "type": "organization"},
        ],
        "constitutional_basis": constitutional_basis or ["1A-free-speech"],
        "lead_type": lead_type,
        "institution": institution,
        "jurisdiction": jurisdiction,
    }


def _make_event_mock(
    *,
    event_id: uuid.UUID | None = None,
    source_id: str = "rss_fire",
    title: str = "Professor fired for speech at UC Berkeley",
    severity: str = "medium",
) -> MagicMock:
    """Create a mock Event object with mutable metadata."""
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.source_id = source_id
    event.title = title
    event.severity = severity
    event.summary = "A professor was terminated after expressing political views."
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version_id = uuid.uuid4()

    # Mutable metadata that the enrichment pipeline writes to
    event.metadata_ = {}

    # Plan version with CAL plan
    event.plan_version = MagicMock()
    event.plan_version.plan_id = _CAL_PLAN_ID
    event.plan_version.content = _PLAN_CONTENT

    return event


# ---------------------------------------------------------------------------
# End-to-end prospecting pipeline test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prospecting_pipeline_end_to_end(respx_mock):
    """Full prospecting pipeline: NLP enrich -> lead match -> report -> email.

    Verifies that data flows correctly between stages: event metadata produced
    by NLP enrichment feeds into lead matching, which creates leads consumed
    by report generation, which produces a PDF sent via email.
    """
    # ---- Stage 0: Setup mock events ----
    event1 = _make_event_mock(
        title="Professor fired for speech at UC Berkeley",
        source_id="rss_fire",
        severity="high",
    )
    event2 = _make_event_mock(
        title="Student expelled for religious expression at UCLA",
        source_id="x_cal_california",
        severity="medium",
    )

    # ---- Stage 1: NLP Enrichment (CAL mode) ----
    # Simulate what _enrich_event_async does: call vLLM, validate, write metadata
    vllm_response1 = _make_vllm_cal_response(
        summary="Professor terminated after political speech.",
        constitutional_basis=["1A-free-speech"],
        institution="UC Berkeley",
        jurisdiction="CA",
        lead_type="incident",
    )
    vllm_response2 = _make_vllm_cal_response(
        summary="Student expelled for wearing religious garments.",
        constitutional_basis=["1A-religion", "14A-equal-protection"],
        institution="UCLA",
        jurisdiction="CA",
        lead_type="incident",
    )

    # Apply enrichment to events (same logic as _enrich_event_async)
    for event, vllm_resp in [(event1, vllm_response1), (event2, vllm_response2)]:
        event.nlp_summary = vllm_resp["summary"]
        event.nlp_relevance = vllm_resp["relevance"]

        cal_fields = _validate_constitutional_fields(vllm_resp)
        meta = dict(event.metadata_ or {})
        meta["constitutional_basis"] = cal_fields["constitutional_basis"]
        meta["lead_type"] = cal_fields["lead_type"]
        meta["institution"] = cal_fields["institution"]
        meta["jurisdiction"] = cal_fields["jurisdiction"]
        event.metadata_ = meta

    # Verify enrichment produced correct metadata
    assert event1.metadata_["constitutional_basis"] == ["1A-free-speech"]
    assert event1.metadata_["lead_type"] == "incident"
    assert event1.metadata_["institution"] == "UC Berkeley"
    assert event1.metadata_["jurisdiction"] == "CA"
    assert event1.nlp_summary == "Professor terminated after political speech."

    assert event2.metadata_["constitutional_basis"] == ["1A-religion", "14A-equal-protection"]
    assert event2.metadata_["institution"] == "UCLA"

    # ---- Stage 2: Lead Matching ----
    # Use _build_matcher_config (same helper the worker uses) to validate
    # the plan-content -> matcher-config translation path.
    config = _build_matcher_config(_PLAN_CONTENT, _CAL_PLAN_ID)
    matcher = LeadMatcher(config)

    # Mock DB session for lead matching
    db = AsyncMock()
    # No existing leads (first call returns None for fingerprint lookup)
    lead_lookup_result = MagicMock()
    lead_lookup_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=lead_lookup_result)

    created_leads = []

    def capture_lead(obj):
        from osint_core.models.lead import Lead
        if isinstance(obj, Lead):
            created_leads.append(obj)

    db.add = MagicMock(side_effect=capture_lead)

    lead1 = await matcher.match_event_to_lead(event1, db)
    lead2 = await matcher.match_event_to_lead(event2, db)

    # Verify leads were created with correct data flow from enrichment
    assert lead1 is not None, "Lead 1 should be created (above threshold)"
    assert lead2 is not None, "Lead 2 should be created (above threshold)"

    assert lead1.lead_type == "incident"
    assert lead1.institution == "UC Berkeley"
    assert lead1.jurisdiction == "CA"
    assert lead1.constitutional_basis == ["1A-free-speech"]
    assert lead1.plan_id == _CAL_PLAN_ID
    assert lead1.confidence > 0.0
    assert lead1.confidence <= 1.0
    assert event1.id in lead1.event_ids

    assert lead2.institution == "UCLA"
    assert "1A-religion" in lead2.constitutional_basis
    assert "14A-equal-protection" in lead2.constitutional_basis

    # Verify confidence scoring uses entity completeness from metadata
    completeness1 = _entity_completeness(event1)
    assert completeness1 > 0.0, "Event with full metadata should have entity completeness > 0"

    # ---- Stage 3: Report Generation ----
    # Test that leads flow into report context correctly
    from osint_core.services.prospecting_report import (
        _fallback_narrative,
        _render_pdf_html,
    )

    # Use fallback narrative (no real vLLM) to test the rendering pipeline
    lead_contexts = []
    for lead in [lead1, lead2]:
        sections = _fallback_narrative(lead)
        lead_contexts.append({
            "lead_type": lead.lead_type,
            "title": lead.title,
            "summary": lead.summary,
            "constitutional_basis": lead.constitutional_basis or [],
            "jurisdiction": lead.jurisdiction,
            "institution": lead.institution,
            "severity": lead.severity,
            "confidence": lead.confidence,
            "sections": sections,
            "source_citations": [],
            "legal_citations": [],
        })

    summary_stats = {
        "total_leads": 2,
        "incidents": 2,
        "policies": 0,
        "high_priority_count": 1,
        "by_jurisdiction": {"CA": 2},
    }

    now = datetime.now(UTC)
    ct_now = now.astimezone(ZoneInfo("America/Chicago"))
    tz_abbr = ct_now.strftime("%Z")
    report_context = {
        "report_date": ct_now.strftime(f"%B %d, %Y — %I:%M %p {tz_abbr}"),
        "report_period": f"Through {ct_now.strftime('%B %d, %Y')}",
        "summary": summary_stats,
        "leads": lead_contexts,
        "all_source_citations": None,
        "all_legal_citations": None,
    }

    # Render HTML from template (exercises real Jinja2 template)
    html = _render_pdf_html(report_context)
    assert isinstance(html, str)
    assert len(html) > 100, "Report HTML should be substantial"

    # Verify lead data flowed into the rendered HTML
    assert "UC Berkeley" in html
    assert "UCLA" in html
    assert "incident" in html.lower()

    # ---- Stage 4: Email Notification (mocked Resend API) ----
    # Mock the Resend API endpoint
    respx_mock.post("https://api.resend.com/emails").mock(
        return_value=httpx.Response(200, json={"id": "email-123"})
    )

    notifier = ResendNotifier(
        api_key="re_test_fake_key",
        from_email="reports@cal.example.com",
    )

    # Simulate sending the report (use fake PDF bytes since WeasyPrint
    # may not be available in CI)
    fake_pdf = b"%PDF-1.4 fake content for integration test"
    executive_summary = f"Report generated with 2 leads on {now.strftime('%B %d, %Y')}."

    sent = await notifier.send_report(
        pdf_bytes=fake_pdf,
        executive_summary=executive_summary,
        recipients=["legal@cal.example.com", "ops@cal.example.com"],
    )

    assert sent is True, "Email should be sent successfully"

    # Verify the Resend API was called with correct payload structure
    assert respx_mock.calls.call_count == 1
    request = respx_mock.calls[0].request
    body = json.loads(request.content)
    assert body["from"] == "reports@cal.example.com"
    assert body["to"] == ["legal@cal.example.com", "ops@cal.example.com"]
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["type"] == "application/pdf"
    assert "Executive Summary" in body["html"]


# ---------------------------------------------------------------------------
# Data flow verification tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_enrichment_metadata_flows_to_lead_fields():
    """Verify that specific NLP enrichment metadata fields map correctly
    to Lead model fields through the matching pipeline."""
    event = _make_event_mock(severity="high")

    # Simulate enrichment with policy-type lead
    event.nlp_summary = "University enacts new speech code restricting campus discourse."
    event.nlp_relevance = "relevant"
    event.metadata_ = {
        "constitutional_basis": ["1A-free-speech", "1A-assembly"],
        "lead_type": "policy",
        "institution": "University of Texas at Austin",
        "jurisdiction": "TX",
    }

    config = LeadMatcherConfig(
        plan_id=_CAL_PLAN_ID,
        confidence_threshold=0.1,
        source_reputation={"rss_fire": 0.9},
    )
    matcher = LeadMatcher(config)

    db = AsyncMock()
    lead_lookup = MagicMock()
    lead_lookup.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=lead_lookup)
    db.add = MagicMock()

    lead = await matcher.match_event_to_lead(event, db)

    assert lead is not None
    # Verify metadata -> lead field mapping
    assert lead.lead_type == "policy"
    assert lead.institution == "University of Texas at Austin"
    assert lead.jurisdiction == "TX"
    assert "1A-free-speech" in lead.constitutional_basis
    assert "1A-assembly" in lead.constitutional_basis
    assert lead.title == event.title
    assert lead.summary == event.nlp_summary
    assert lead.plan_id == _CAL_PLAN_ID
    assert lead.status == "new"


@pytest.mark.integration
async def test_confidence_scoring_reflects_entity_completeness():
    """Events with more complete entity metadata produce higher confidence scores."""
    # Event with full metadata
    full_event = _make_event_mock(severity="high")
    full_event.metadata_ = {
        "constitutional_basis": ["1A-free-speech"],
        "lead_type": "incident",
        "institution": "Stanford University",
        "jurisdiction": "CA",
    }

    # Event with minimal metadata
    sparse_event = _make_event_mock(severity="low")
    sparse_event.metadata_ = {
        "lead_type": "incident",
    }

    full_completeness = _entity_completeness(full_event)
    sparse_completeness = _entity_completeness(sparse_event)

    assert full_completeness > sparse_completeness, (
        f"Full metadata ({full_completeness}) should yield higher completeness "
        f"than sparse metadata ({sparse_completeness})"
    )

    # Verify this difference propagates to confidence scores
    full_confidence = compute_confidence(
        source_count=1,
        source_types={"rss"},
        severity="high",
        entity_completeness=full_completeness,
        source_reputation={"rss_fire": 0.9},
        source_ids=["rss_fire"],
    )
    sparse_confidence = compute_confidence(
        source_count=1,
        source_types={"rss"},
        severity="low",
        entity_completeness=sparse_completeness,
    )

    assert full_confidence > sparse_confidence, (
        f"Full entity confidence ({full_confidence}) should exceed "
        f"sparse ({sparse_confidence})"
    )


@pytest.mark.integration
async def test_constitutional_field_validation_in_enrichment():
    """Verify that _validate_constitutional_fields correctly filters
    invalid values, ensuring only valid data reaches lead matching."""
    # Valid response
    valid = _validate_constitutional_fields({
        "constitutional_basis": ["1A-free-speech", "14A-due-process"],
        "lead_type": "incident",
        "institution": "MIT",
        "jurisdiction": "DC",
    })
    assert valid["constitutional_basis"] == ["1A-free-speech", "14A-due-process"]
    assert valid["lead_type"] == "incident"
    assert valid["institution"] == "MIT"
    assert valid["jurisdiction"] == "DC"

    # Invalid basis labels are filtered out
    mixed = _validate_constitutional_fields({
        "constitutional_basis": ["1A-free-speech", "INVALID-LABEL", "parental-rights"],
        "lead_type": "incident",
        "institution": "Harvard",
        "jurisdiction": "california",  # alias, should resolve to CA
    })
    assert mixed["constitutional_basis"] == ["1A-free-speech", "parental-rights"]
    assert mixed["jurisdiction"] == "CA"

    # Completely invalid data returns safe defaults
    invalid = _validate_constitutional_fields({
        "constitutional_basis": "not-a-list",
        "lead_type": "invalid_type",
        "institution": "",
        "jurisdiction": "XX",
    })
    assert invalid["constitutional_basis"] == []
    assert invalid["lead_type"] is None
    assert invalid["institution"] is None
    assert invalid["jurisdiction"] is None


@pytest.mark.integration
async def test_report_context_preserves_lead_data(respx_mock):
    """Verify that lead data is preserved through report context assembly
    and appears in the rendered HTML output."""
    event = _make_event_mock(severity="critical")
    event.nlp_summary = "Severe free speech violation at state university."
    event.nlp_relevance = "relevant"
    event.metadata_ = {
        "constitutional_basis": ["1A-free-speech", "14A-due-process"],
        "lead_type": "incident",
        "institution": "University of Minnesota",
        "jurisdiction": "MN",
    }

    config = LeadMatcherConfig(
        plan_id=_CAL_PLAN_ID,
        confidence_threshold=0.1,
        source_reputation={"rss_fire": 0.9},
    )
    matcher = LeadMatcher(config)

    db = AsyncMock()
    lead_lookup = MagicMock()
    lead_lookup.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=lead_lookup)
    db.add = MagicMock()

    lead = await matcher.match_event_to_lead(event, db)
    assert lead is not None

    from osint_core.services.prospecting_report import (
        _fallback_narrative,
        _render_pdf_html,
    )

    sections = _fallback_narrative(lead)
    lead_context = {
        "lead_type": lead.lead_type,
        "title": lead.title,
        "summary": lead.summary,
        "constitutional_basis": lead.constitutional_basis or [],
        "jurisdiction": lead.jurisdiction,
        "institution": lead.institution,
        "severity": lead.severity,
        "confidence": lead.confidence,
        "sections": sections,
        "source_citations": [],
        "legal_citations": [],
    }

    now = datetime.now(UTC)
    ct_now = now.astimezone(ZoneInfo("America/Chicago"))
    tz_abbr = ct_now.strftime("%Z")
    context = {
        "report_date": ct_now.strftime(f"%B %d, %Y — %I:%M %p {tz_abbr}"),
        "report_period": f"Through {ct_now.strftime('%B %d, %Y')}",
        "summary": {
            "total_leads": 1,
            "incidents": 1,
            "policies": 0,
            "high_priority_count": 1,
            "by_jurisdiction": {"MN": 1},
        },
        "leads": [lead_context],
        "all_source_citations": None,
        "all_legal_citations": None,
    }

    html = _render_pdf_html(context)

    # Lead data should flow through to the rendered HTML
    assert "University of Minnesota" in html
    assert "MN" in html
    assert "1A-free-speech" in html
    assert "14A-due-process" in html
    assert "incident" in html.lower()
