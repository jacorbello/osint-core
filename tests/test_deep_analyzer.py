"""Tests for DeepAnalyzer service."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.services.deep_analyzer import (
    _MAX_RESPONSE_BYTES,
    DeepAnalyzer,
    _is_ip_private,
    _resolve_and_validate,
    _safe_get_with_redirects,
)


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


def _make_event(
    *,
    minio_uri: str | None = "minio://osint-artifacts/policy.html",
    source_id: str = "univ_uc",
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.metadata_ = {"minio_uri": minio_uri, "document_type": "html"} if minio_uri else {}
    event.raw_excerpt = "https://example.edu/policy"
    event.title = "Test Policy"
    event.source_id = source_id
    event.nlp_summary = "NLP summary of event."
    return event


SAMPLE_POLICY_ANALYSIS = {
    "provisions": [
        {
            "section_reference": "\u00a7 4.2",
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

SAMPLE_SCREENING_RELEVANT = {
    "relevant": True,
    "language": "en",
    "lead_title": "UC Berkeley Speech Policy",
    "document_summary": "Policy regulating campus speech.",
    "overall_assessment": "Contains provisions restricting free speech.",
    "flagged_sections": ["\u00a7 4.2 - Pronoun Requirements", "\u00a7 5.1 - Protest Zones"],
}

SAMPLE_SCREENING_IRRELEVANT = {
    "relevant": False,
    "language": "en",
    "lead_title": "UC Berkeley IT Procurement Policy",
    "document_summary": "Administrative IT procurement procedures.",
    "overall_assessment": "No constitutional issues found.",
    "flagged_sections": [],
}

SAMPLE_SCREENING_NON_ENGLISH = {
    "relevant": True,
    "language": "es",
    "lead_title": "Pol\u00edtica Universitaria",
    "document_summary": "Spanish language policy.",
    "overall_assessment": "Cannot assess \u2014 non-English.",
    "flagged_sections": [],
}

SAMPLE_PROVISION_RESULT_1 = {
    "section_reference": "\u00a7 4.2",
    "quoted_language": "Students must use preferred pronouns.",
    "constitutional_issue": "Compelled speech under First Amendment",
    "constitutional_basis": "1A-free-speech",
    "severity": "high",
    "affected_population": "All students",
    "facial_or_as_applied": "facial",
    "sources_cited": ["Janus v. AFSCME"],
}

SAMPLE_PROVISION_RESULT_2 = {
    "section_reference": "\u00a7 5.1",
    "quoted_language": "All protests must occur in designated zones.",
    "constitutional_issue": "Restriction on assembly in public forum",
    "constitutional_basis": "1A-assembly",
    "severity": "medium",
    "affected_population": "All students and faculty",
    "facial_or_as_applied": "facial",
    "sources_cited": ["Tinker v. Des Moines"],
}


class TestAnalyzePolicy:
    @pytest.mark.asyncio
    async def test_analyzes_policy_document(self) -> None:
        """Existing test adapted for two-pass flow."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        with (
            patch.object(
                analyzer,
                "_retrieve_document",
                new_callable=AsyncMock,
                return_value=b"<p>Policy text with enough content to pass gates</p>" * 5,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch.object(
                analyzer,
                "_screen_document",
                new_callable=AsyncMock,
                return_value=SAMPLE_SCREENING_RELEVANT,
            ),
            patch.object(
                analyzer,
                "_analyze_provision",
                new_callable=AsyncMock,
                side_effect=[SAMPLE_PROVISION_RESULT_1, SAMPLE_PROVISION_RESULT_2],
            ),
            patch.object(
                analyzer,
                "_attach_precedent",
                new_callable=AsyncMock,
                side_effect=lambda a: a,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["actionable"] is True
        assert len(result["provisions"]) == 2  # two flagged sections
        assert result["provisions"][0]["section_reference"] == "\u00a7 4.2"
        assert result["provisions"][1]["section_reference"] == "\u00a7 5.1"

    @pytest.mark.asyncio
    async def test_actionable_policy_has_completed_status(self) -> None:
        """JSONB analysis_status must be 'completed' (not 'complete')."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        with (
            patch.object(
                analyzer,
                "_retrieve_document",
                new_callable=AsyncMock,
                return_value=b"<p>Policy text with enough content to pass gates</p>" * 5,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch.object(
                analyzer,
                "_screen_document",
                new_callable=AsyncMock,
                return_value=SAMPLE_SCREENING_RELEVANT,
            ),
            patch.object(
                analyzer,
                "_analyze_provision",
                new_callable=AsyncMock,
                side_effect=[SAMPLE_PROVISION_RESULT_1, SAMPLE_PROVISION_RESULT_2],
            ),
            patch.object(
                analyzer,
                "_attach_precedent",
                new_callable=AsyncMock,
                side_effect=lambda a: a,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["analysis_status"] == "completed"

    @pytest.mark.asyncio
    async def test_non_actionable_policy(self) -> None:
        """Irrelevant document returns not_actionable via screening."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        with (
            patch.object(
                analyzer,
                "_retrieve_document",
                new_callable=AsyncMock,
                return_value=b"<p>Admin stuff repeated many times</p>" * 5,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch.object(
                analyzer,
                "_screen_document",
                new_callable=AsyncMock,
                return_value=SAMPLE_SCREENING_IRRELEVANT,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["actionable"] is False
        assert result["provisions"] == []
        assert result["analysis_status"] == "not_actionable"


class TestAnalyzeIncident:
    @pytest.mark.asyncio
    async def test_analyzes_incident(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="incident")
        event = _make_event(minio_uri=None, source_id="rss_fire")
        event.raw_excerpt = "https://example.com/article"

        with (
            patch.object(
                analyzer,
                "_fetch_article_content",
                new_callable=AsyncMock,
                return_value="Article about professor firing.",
            ),
            patch(
                "osint_core.services.deep_analyzer.llm_chat_completion",
                new_callable=AsyncMock,
                return_value=json.dumps(SAMPLE_INCIDENT_ANALYSIS),
            ),
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


# ---------------------------------------------------------------
# Pass 1: Screening tests
# ---------------------------------------------------------------


class TestPass1Screening:
    @pytest.mark.asyncio
    async def test_screening_relevant_returns_flagged_sections(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        with patch(
            "osint_core.services.deep_analyzer.llm_chat_completion",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_SCREENING_RELEVANT),
        ):
            result = await analyzer._screen_document(lead, event, "Full document text here.")

        assert result is not None
        assert result["relevant"] is True
        assert result["language"] == "en"
        assert len(result["flagged_sections"]) == 2

    @pytest.mark.asyncio
    async def test_screening_irrelevant_returns_no_sections(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        with patch(
            "osint_core.services.deep_analyzer.llm_chat_completion",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_SCREENING_IRRELEVANT),
        ):
            result = await analyzer._screen_document(lead, event, "Admin procurement policy.")

        assert result is not None
        assert result["relevant"] is False
        assert result["flagged_sections"] == []


# ---------------------------------------------------------------
# Pass 2: Provision analysis tests
# ---------------------------------------------------------------


class TestPass2ProvisionAnalysis:
    @pytest.mark.asyncio
    async def test_analyze_provision_returns_structured_output(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={
            "1A-free-speech": {
                "compelled speech": [
                    {"case": "Janus v. AFSCME", "citation": "585 U.S. 878"}
                ]
            }
        })
        lead = _make_lead()
        event = _make_event()

        with patch(
            "osint_core.services.deep_analyzer.llm_chat_completion",
            new_callable=AsyncMock,
            return_value=json.dumps(SAMPLE_PROVISION_RESULT_1),
        ):
            result = await analyzer._analyze_provision(
                lead, event,
                full_doc="Full doc text with \u00a7 4.2 Students must use preferred pronouns.",
                flagged_section="\u00a7 4.2 - Pronoun Requirements",
                corroborating_events=[],
            )

        assert result is not None
        assert result["section_reference"] == "\u00a7 4.2"
        assert result["constitutional_basis"] == "1A-free-speech"
        assert "sources_cited" in result

    def test_extract_section_text_finds_match(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        full_text = (
            "Preamble text.\n\n"
            "\u00a7 4.2 Pronoun Requirements\n"
            "Students must use preferred pronouns in all communications.\n\n"
            "\u00a7 5.1 Protest Zones\n"
            "All protests must occur in designated zones."
        )
        result = analyzer._extract_section_text(full_text, "\u00a7 4.2 - Pronoun Requirements")
        assert "Students must use preferred pronouns" in result

    def test_extract_section_text_fuzzy_match(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        full_text = (
            "Introduction text.\n\n"
            "Section 12: Requirements for Student Conduct\n"
            "All students must adhere to conduct standards.\n\n"
            "Section 13: Academic Integrity\n"
            "Cheating is prohibited."
        )
        # Fuzzy: ref uses different formatting than actual text
        result = analyzer._extract_section_text(
            full_text, "Section 12 - Student Conduct Requirements",
        )
        assert "conduct standards" in result


# ---------------------------------------------------------------
# Two-pass flow integration tests
# ---------------------------------------------------------------


class TestTwoPassFlow:
    @pytest.mark.asyncio
    async def test_full_policy_analysis_two_pass(self) -> None:
        """Screening + 2 provision calls = 3 total LLM calls."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        doc_bytes = b"<p>Policy text with enough content to pass quality gates</p>" * 5

        screening_response = json.dumps(SAMPLE_SCREENING_RELEVANT)
        provision_response_1 = json.dumps(SAMPLE_PROVISION_RESULT_1)
        provision_response_2 = json.dumps(SAMPLE_PROVISION_RESULT_2)

        llm_mock = AsyncMock(
            side_effect=[screening_response, provision_response_1, provision_response_2],
        )

        with (
            patch.object(
                analyzer, "_retrieve_document",
                new_callable=AsyncMock, return_value=doc_bytes,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch(
                "osint_core.services.deep_analyzer.llm_chat_completion",
                llm_mock,
            ),
            patch.object(
                analyzer, "_attach_precedent",
                new_callable=AsyncMock, side_effect=lambda a: a,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["actionable"] is True
        assert len(result["provisions"]) == 2
        # 1 screening + 2 provision = 3 LLM calls
        assert llm_mock.call_count == 3

    @pytest.mark.asyncio
    async def test_irrelevant_document_skips_pass2(self) -> None:
        """Irrelevant screening result = only 1 LLM call."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        doc_bytes = b"<p>Admin procurement policy text repeated here</p>" * 5

        llm_mock = AsyncMock(return_value=json.dumps(SAMPLE_SCREENING_IRRELEVANT))

        with (
            patch.object(
                analyzer, "_retrieve_document",
                new_callable=AsyncMock, return_value=doc_bytes,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch(
                "osint_core.services.deep_analyzer.llm_chat_completion",
                llm_mock,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["actionable"] is False
        assert result["analysis_status"] == "not_actionable"
        assert llm_mock.call_count == 1

    @pytest.mark.asyncio
    async def test_quality_gate_garbled_text_returns_extraction_failed(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        # Garbled bytes -- lots of replacement chars
        garbled = ("\ufffd" * 100).encode("utf-8")

        with (
            patch.object(
                analyzer, "_retrieve_document",
                new_callable=AsyncMock, return_value=garbled,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["analysis_status"] == "extraction_failed"

    @pytest.mark.asyncio
    async def test_quality_gate_non_english_returns_non_english(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()

        # Text that passes encoding but is non-English
        spanish_text = (
            "Esta es una pol\u00edtica universitaria sobre los"
            " procedimientos administrativos y la gesti\u00f3n"
            " de recursos humanos en la universidad. "
        ) * 5
        doc_bytes = f"<p>{spanish_text}</p>".encode()

        with (
            patch.object(
                analyzer, "_retrieve_document",
                new_callable=AsyncMock, return_value=doc_bytes,
            ),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch(
                "osint_core.services.document_extractor.DocumentExtractor.detect_language",
                return_value="es",
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result is not None
        assert result["analysis_status"] == "non_english"

    @pytest.mark.asyncio
    async def test_minio_fails_falls_back_to_url(self) -> None:
        """When MinIO retrieval fails, fetch from source URL."""
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead()
        event = _make_event()
        event.metadata_["url"] = "https://example.edu/policy.html"

        doc_html = "<p>Policy fetched from URL with enough content to pass gates</p>" * 5
        fetch_mock = AsyncMock(return_value=doc_html.encode("utf-8"))

        with (
            patch.object(
                analyzer, "_retrieve_document",
                new_callable=AsyncMock, return_value=None,
            ),
            patch.object(
                analyzer, "_fetch_url_content",
                fetch_mock,
            ),
            patch.object(
                analyzer, "_screen_document",
                new_callable=AsyncMock, return_value=SAMPLE_SCREENING_IRRELEVANT,
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)
            # Verify _fetch_url_content was called
            fetch_mock.assert_called_once()

        assert result is not None


# ---------------------------------------------------------------
# Citations and Severity rollup
# ---------------------------------------------------------------


class TestCitationsAndSeverity:
    def test_build_citations_from_provisions(self) -> None:
        provisions = [
            {
                "section_reference": "\u00a7 4.2",
                "quoted_language": "Students must use preferred pronouns.",
                "constitutional_basis": "1A-free-speech",
                "severity": "high",
                "sources_cited": ["Janus v. AFSCME"],
            },
            {
                "section_reference": "\u00a7 5.1",
                "quoted_language": "All protests must occur in designated zones.",
                "constitutional_basis": "1A-assembly",
                "severity": "medium",
                "sources_cited": ["Tinker v. Des Moines"],
            },
        ]
        legal_precedent = [
            {
                "case_name": "Janus v. AFSCME",
                "citation": "585 U.S. 878",
                "courtlistener_url": "https://courtlistener.com/1",
                "verified": True,
                "holding_summary": "Compelled speech violates 1A",
            },
            {
                "case_name": "Tinker v. Des Moines",
                "citation": "393 U.S. 503",
                "courtlistener_url": "https://courtlistener.com/2",
                "verified": True,
                "holding_summary": "Students retain speech rights",
            },
        ]

        result = DeepAnalyzer.build_citations(
            provisions,
            legal_precedent,
            source_url="https://example.edu/policy",
            document_title="UC Berkeley Speech Policy",
            minio_uri="minio://osint-artifacts/policy.html",
        )

        assert len(result["source_citations"]) == 2
        assert len(result["legal_citations"]) == 2

        # Check ref_ids are sequential starting from 1
        all_ids = [c["ref_id"] for c in result["source_citations"]] + [
            c["ref_id"] for c in result["legal_citations"]
        ]
        assert all_ids == [1, 2, 3, 4]

        # Check source citation fields
        src = result["source_citations"][0]
        assert src["type"] == "policy_document"
        assert src["title"] == "UC Berkeley Speech Policy"
        assert src["section"] == "\u00a7 4.2"
        assert src["archived_artifact_id"] == "minio://osint-artifacts/policy.html"

        # Check legal citation fields
        legal = result["legal_citations"][0]
        assert legal["type"] == "case_law"
        assert legal["case_name"] == "Janus v. AFSCME"
        assert legal["verified"] is True
        assert legal["relevance"] == "Compelled speech violates 1A"

    def test_build_citations_deduplicates_by_section(self) -> None:
        provisions = [
            {"section_reference": "\u00a7 4.2", "severity": "high"},
            {"section_reference": "\u00a7 4.2", "severity": "medium"},
            {"section_reference": "\u00a7 5.1", "severity": "low"},
        ]
        result = DeepAnalyzer.build_citations(
            provisions, [],
            source_url="https://example.edu/policy",
            document_title="Test",
        )
        assert len(result["source_citations"]) == 2
        sections = [c["section"] for c in result["source_citations"]]
        assert sections == ["\u00a7 4.2", "\u00a7 5.1"]

    def test_compute_max_severity(self) -> None:
        assert DeepAnalyzer.compute_max_severity(
            [{"severity": "info"}, {"severity": "high"}, {"severity": "medium"}]
        ) == "high"

    def test_compute_max_severity_empty(self) -> None:
        assert DeepAnalyzer.compute_max_severity([]) == "info"

    def test_compute_max_severity_critical(self) -> None:
        assert DeepAnalyzer.compute_max_severity(
            [{"severity": "low"}, {"severity": "critical"}]
        ) == "critical"

    def test_compute_max_severity_all_same(self) -> None:
        assert DeepAnalyzer.compute_max_severity(
            [{"severity": "medium"}, {"severity": "medium"}]
        ) == "medium"


# ---------------------------------------------------------------
# End-to-end integration test
# ---------------------------------------------------------------


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_full_pipeline_produces_report_ready_output(self):
        """Verify full pipeline from HTML extraction through citations."""
        analyzer = DeepAnalyzer(
            precedent_map={"1A-free-speech": {"speech_codes": [
                {"case": "Tinker v. Des Moines", "citation": "393 U.S. 503 (1969)"},
            ]}},
            courtlistener=AsyncMock(),
        )
        analyzer._courtlistener.lookup_precedent = AsyncMock(return_value=[])

        # Create lead and event mocks
        lead = MagicMock(id=uuid.uuid4(), title="[UC System] View PolicyPolitical Activities",
                         institution="University of California System", jurisdiction="CA",
                         lead_type="policy", event_ids=[uuid.uuid4()], citations=None,
                         deep_analysis=None, analysis_status="pending", severity="info")
        event = MagicMock(id=lead.event_ids[0], source_id="univ_uc", title="UC Policy",
                          metadata_={"minio_uri": "minio://osint-artifacts/policies/abc.html",
                                     "url": "https://policy.ucop.edu/doc/3000127",
                                     "title": "Political Activities Policy"},
                          raw_excerpt=None, created_at="2026-04-01T12:00:00Z")

        html = b"""<html><body>
        <h1>University of California Policy on Political Activities</h1>
        <h2>Section 4.2 Use of Facilities</h2>
        <p>No University facility shall be used for political activities other than
        those open discussion and meeting areas provided for in campus regulations.</p>
        <h2>Section 5.0 Administrative Procedures</h2>
        <p>Standard procedures for facility reservations.</p>
        </body></html>"""

        screening = {
            "relevant": True, "language": "en",
            "lead_title": "UC Political Activities \u2014 Facial 1A Speech Restrictions",
            "document_summary": "Policy restricts political activities on campus.",
            "overall_assessment": "Likely unconstitutional facial restriction.",
            "flagged_sections": [
                "Section 4.2 - Use of Facilities (restricts political speech)",
            ],
        }
        provision = {
            "section_reference": "\u00a7 4.2",
            "quoted_language": "No University facility shall be used for political activities.",
            "constitutional_issue": "Content-based restriction on political speech",
            "constitutional_basis": "1A-free-speech",
            "severity": "high",
            "affected_population": "University community",
            "facial_or_as_applied": "facial",
            "sources_cited": [
                {
                    "type": "policy_document",
                    "url": "https://policy.ucop.edu/doc/3000127",
                    "section": "\u00a7 4.2",
                },
            ],
        }

        with (
            patch.object(analyzer, "_retrieve_document", new_callable=AsyncMock, return_value=html),
            patch(
                "osint_core.services.deep_analyzer.llm_chat_completion",
                new_callable=AsyncMock,
                side_effect=[json.dumps(screening), json.dumps(provision)],
            ),
        ):
            result = await analyzer.analyze_lead(lead, event)

        # Verify complete output
        assert result is not None
        assert result["relevant"] is True
        assert result["actionable"] is True
        expected_title = "UC Political Activities \u2014 Facial 1A Speech Restrictions"
        assert result["lead_title"] == expected_title
        assert len(result["provisions"]) == 1
        assert result["provisions"][0]["severity"] == "high"
        assert result["provisions"][0]["quoted_language"] != ""

        # Verify severity rollup
        assert DeepAnalyzer.compute_max_severity(result["provisions"]) == "high"

        # Verify citations can be built
        citations = DeepAnalyzer.build_citations(
            result["provisions"], [],
            source_url="https://policy.ucop.edu/doc/3000127",
            document_title=result["lead_title"],
            minio_uri="minio://osint-artifacts/policies/abc.html",
        )
        assert len(citations["source_citations"]) >= 1
        assert citations["source_citations"][0]["url"] == "https://policy.ucop.edu/doc/3000127"


# ---------------------------------------------------------------
# Redirect validation (SSRF protection)
# ---------------------------------------------------------------


class TestIsIpPrivate:
    def test_loopback_ipv4(self) -> None:
        assert _is_ip_private("127.0.0.1") is True

    def test_loopback_ipv6(self) -> None:
        assert _is_ip_private("::1") is True

    def test_private_10(self) -> None:
        assert _is_ip_private("10.0.0.1") is True

    def test_private_172(self) -> None:
        assert _is_ip_private("172.16.0.1") is True

    def test_private_192(self) -> None:
        assert _is_ip_private("192.168.1.1") is True

    def test_link_local(self) -> None:
        assert _is_ip_private("169.254.169.254") is True

    def test_public_ip(self) -> None:
        assert _is_ip_private("8.8.8.8") is False

    def test_hostname_not_ip(self) -> None:
        assert _is_ip_private("example.com") is False


async def _fake_public_getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
    """Return a deterministic public IP for any hostname, avoiding real DNS."""
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


class TestSafeGetWithRedirects:
    @pytest.fixture(autouse=True)
    def _patch_dns(self, monkeypatch):
        """Patch loop.getaddrinfo so tests never perform real DNS resolution."""
        import asyncio

        _orig_get_loop = asyncio.get_running_loop

        def _patched_get_running_loop():
            loop = _orig_get_loop()
            loop.getaddrinfo = _fake_public_getaddrinfo
            return loop

        monkeypatch.setattr(asyncio, "get_running_loop", _patched_get_running_loop)

    @pytest.mark.asyncio
    async def test_redirect_to_metadata_endpoint_blocked(self) -> None:
        """SSRF: redirect to cloud metadata endpoint must be blocked."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data"},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://example.com/article"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_redirect_to_loopback_blocked(self) -> None:
        """SSRF: redirect to 127.0.0.1 must be blocked."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                301,
                headers={"Location": "http://127.0.0.1:8080/admin"},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/story"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_redirect_to_file_scheme_blocked(self) -> None:
        """Non-http(s) scheme must be rejected."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                302,
                headers={"Location": "file:///etc/passwd"},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://evil.com/redirect"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_max_redirects_enforced(self) -> None:
        """Chain of 6 redirects must be stopped at max depth (5)."""
        call_count = 0

        def redirect_chain(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                302,
                headers={"Location": f"http://news.example.com/hop{call_count}"},
            )

        transport = httpx.MockTransport(redirect_chain)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/start"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_legitimate_redirect_followed(self) -> None:
        """Normal redirect to a public news site must succeed."""
        def handler(req: httpx.Request) -> httpx.Response:
            if "original" in str(req.url):
                return httpx.Response(
                    301,
                    headers={"Location": "http://news.example.com/final-article"},
                )
            return httpx.Response(200, text="<p>Article content</p>")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/original"
            )
        assert resp is not None
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_redirect_returns_directly(self) -> None:
        """Non-redirect response returned as-is."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="<p>Direct content</p>")
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://example.com/page"
            )
        assert resp is not None
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_redirect_to_private_10_network_blocked(self) -> None:
        """Redirect to 10.x.x.x must be blocked."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                302,
                headers={"Location": "http://10.0.0.5/internal"},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://example.com/redir"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_initial_url_with_private_ip_blocked(self) -> None:
        """Even the initial URL should be validated."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text="should not reach")
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://192.168.1.1/admin"
            )
        assert resp is None


class TestFetchUrlContentAllowlist:
    """Tests for _fetch_url_content domain allowlist enforcement."""

    @pytest.fixture()
    def analyzer(self) -> DeepAnalyzer:
        return DeepAnalyzer(precedent_map={})

    @pytest.mark.asyncio
    async def test_blocked_domain_returns_none(self, analyzer: DeepAnalyzer) -> None:
        """A .com URL is rejected without making any HTTP request."""
        with patch("osint_core.services.deep_analyzer.httpx.AsyncClient") as mock_client:
            result = await analyzer._fetch_url_content("https://evil.com/payload")

        assert result is None
        mock_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_gov_domain_returns_content(self, analyzer: DeepAnalyzer) -> None:
        """.gov URL passes allowlist and returns fetched content."""
        import respx

        with (
            respx.mock,
            patch(
                "osint_core.services.deep_analyzer._resolve_and_validate",
                new_callable=AsyncMock,
                return_value="93.184.216.34",
            ),
        ):
            respx.get("https://93.184.216.34/doc.pdf").mock(
                return_value=httpx.Response(200, content=b"policy document bytes")
            )
            result = await analyzer._fetch_url_content("https://example.gov/doc.pdf")

        assert result == b"policy document bytes"


# ---------------------------------------------------------------
# Response size limit tests
# ---------------------------------------------------------------


class TestResponseSizeLimit:
    def test_default_limit_is_10mb(self) -> None:
        assert _MAX_RESPONSE_BYTES == 10 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_fetch_url_content_rejects_oversized_content_length(self) -> None:
        """Content-Length exceeding limit causes immediate abort (no body download)."""
        from osint_core.services.deep_analyzer import _check_content_length

        oversized = str(_MAX_RESPONSE_BYTES + 1)
        resp = httpx.Response(
            200,
            headers={"Content-Length": oversized},
            content=b"should not be read",
        )
        # Verify the Content-Length check rejects this
        assert _check_content_length(resp.headers, "https://example.edu/big.pdf") is True

    @pytest.mark.asyncio
    async def test_fetch_url_content_allows_normal_sized_response(self) -> None:
        """Response within limit returns body via _read_body_with_limit."""
        from osint_core.services.deep_analyzer import _check_content_length, _read_body_with_limit

        body = b"<p>Normal policy document</p>"
        resp = httpx.Response(
            200,
            headers={"Content-Length": str(len(body))},
            content=body,
        )
        assert _check_content_length(resp.headers, "https://example.edu/policy.html") is False
        result = await _read_body_with_limit(resp, "https://example.edu/policy.html")
        assert result == body

    @pytest.mark.asyncio
    async def test_streaming_abort_when_no_content_length(self) -> None:
        """Streaming body exceeding limit is aborted when Content-Length is absent."""
        from osint_core.services.deep_analyzer import _read_body_with_limit

        chunk_size = 1024 * 1024  # 1 MB chunks
        num_chunks = 11  # 11 MB total > 10 MB limit

        async def _fake_aiter_bytes():
            for _ in range(num_chunks):
                yield b"x" * chunk_size

        resp = MagicMock()
        resp.headers = httpx.Headers({})  # No Content-Length
        resp.aiter_bytes = _fake_aiter_bytes
        resp.aclose = AsyncMock()

        result = await _read_body_with_limit(resp, "https://example.edu/huge.pdf")
        assert result is None
        resp.aclose.assert_awaited_once()

    @pytest.fixture(autouse=True)
    def _patch_dns(self, monkeypatch):
        """Patch loop.getaddrinfo so tests never perform real DNS resolution."""
        import asyncio

        _orig_get_loop = asyncio.get_running_loop

        def _patched_get_running_loop():
            loop = _orig_get_loop()
            loop.getaddrinfo = _fake_public_getaddrinfo
            return loop

        monkeypatch.setattr(asyncio, "get_running_loop", _patched_get_running_loop)

    @pytest.mark.asyncio
    async def test_safe_get_rejects_oversized_content_length(self) -> None:
        """_safe_get_with_redirects rejects responses exceeding size limit."""
        oversized = str(_MAX_RESPONSE_BYTES + 1)

        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                headers={"Content-Length": oversized},
                content=b"should not be read",
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/article"
            )
        assert resp is None

    @pytest.mark.asyncio
    async def test_safe_get_allows_normal_response(self) -> None:
        """_safe_get_with_redirects returns normal-sized responses."""
        body = b"<p>Article content</p>"

        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                headers={"Content-Length": str(len(body))},
                content=body,
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/article"
            )
        assert resp is not None
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_safe_get_streaming_abort_over_limit(self) -> None:
        """_safe_get_with_redirects aborts chunked responses exceeding limit."""
        body = b"x" * (_MAX_RESPONSE_BYTES + 1024)

        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, content=body)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://news.example.com/big-article"
            )
        assert resp is None


# ---------------------------------------------------------------
# DNS rebinding TOCTOU mitigation
# ---------------------------------------------------------------


class TestResolveAndValidate:
    """Unit tests for _resolve_and_validate helper."""

    @pytest.mark.asyncio
    async def test_returns_resolved_ip_for_public_hostname(self) -> None:
        """Public hostname resolution returns the IP string."""
        import asyncio

        async def _fake_resolve(host, port, *, family=0, type=0, proto=0, flags=0):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _fake_resolve

        result = await _resolve_and_validate("http://example.com/page")
        assert result == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_returns_none_for_private_ip_literal(self) -> None:
        result = await _resolve_and_validate("http://192.168.1.1/admin")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_dns_resolves_to_private(self) -> None:
        import asyncio

        async def _resolve_private(host, port, *, family=0, type=0, proto=0, flags=0):
            return [(2, 1, 6, "", ("10.0.0.5", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _resolve_private

        result = await _resolve_and_validate("http://evil.com/payload")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_bad_scheme(self) -> None:
        result = await _resolve_and_validate("ftp://example.com/file")
        assert result is None


class TestDnsRebindingMitigation:
    """Verify that HTTP requests use the pre-validated IP, not a re-resolved one."""

    @pytest.mark.asyncio
    async def test_safe_get_uses_pinned_ip(self) -> None:
        """DNS rebinding: second resolution returns private IP, but request
        must use the first (public) IP captured during validation."""
        import asyncio

        call_count = 0

        async def _rebinding_dns(host, port, *, family=0, type=0, proto=0, flags=0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call (validation): return public IP
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            # Subsequent calls: attacker rebinds to private IP
            return [(2, 1, 6, "", ("10.0.0.5", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _rebinding_dns

        # Track which Host header the request carries
        captured_host = None

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal captured_host
            captured_host = req.headers.get("host")
            return httpx.Response(200, text="<p>OK</p>")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://example.com/article"
            )

        # Request must succeed (the validated IP was public)
        assert resp is not None
        assert resp.status_code == 200
        # Host header must be the original hostname for virtual hosting
        assert captured_host == "example.com"
        # DNS should only be called once (during validation); the pinned IP
        # is used for the actual request without re-resolving
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_url_content_uses_pinned_ip(self) -> None:
        """_fetch_url_content must connect to the pre-validated IP."""
        import asyncio

        call_count = 0

        async def _rebinding_dns(host, port, *, family=0, type=0, proto=0, flags=0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [(2, 1, 6, "", ("93.184.216.34", 0))]
            return [(2, 1, 6, "", ("10.0.0.5", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _rebinding_dns

        analyzer = DeepAnalyzer(precedent_map={})

        with patch(
            "osint_core.services.deep_analyzer.httpx.AsyncClient",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.content = b"<p>Document</p>"
            mock_resp.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await analyzer._fetch_url_content("https://example.edu/policy.pdf")

        assert result is not None
        # Verify DNS was called exactly once (during validation)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_safe_get_redirect_validates_each_hop(self) -> None:
        """Each redirect hop must resolve and validate its target IP."""
        import asyncio

        resolved_hosts: list[str] = []

        async def _tracking_dns(host, port, *, family=0, type=0, proto=0, flags=0):
            resolved_hosts.append(host)
            return [(2, 1, 6, "", ("93.184.216.34", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _tracking_dns

        def handler(req: httpx.Request) -> httpx.Response:
            if "start" in str(req.url):
                return httpx.Response(
                    301, headers={"Location": "http://news.example.com/final"}
                )
            return httpx.Response(200, text="<p>Final</p>")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "http://example.com/start"
            )

        assert resp is not None
        assert resp.status_code == 200
        # Both hops should have been validated via DNS
        assert len(resolved_hosts) == 2

    @pytest.mark.asyncio
    async def test_tls_sni_uses_original_hostname(self) -> None:
        """TLS SNI/certificate validation must check the original hostname."""
        import asyncio

        async def _fake_resolve(host, port, *, family=0, type=0, proto=0, flags=0):
            return [(2, 1, 6, "", ("93.184.216.34", 0))]

        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _fake_resolve

        captured_host = None

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal captured_host
            captured_host = req.headers.get("host")
            return httpx.Response(200, text="<p>Secure</p>")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await _safe_get_with_redirects(
                client, "https://secure.example.com/page"
            )

        assert resp is not None
        # Host header preserves original hostname for TLS SNI
        assert captured_host == "secure.example.com"
