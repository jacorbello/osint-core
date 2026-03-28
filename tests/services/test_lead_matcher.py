"""Tests for the LeadMatcher service."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from osint_core.services.lead_matcher import (
    LeadMatcher,
    LeadMatcherConfig,
    _entity_completeness,
    _normalize_severity,
    _source_type,
    compute_confidence,
    compute_fingerprint,
    compute_incident_fingerprint,
    compute_policy_fingerprint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    source_id: str = "rss_fire",
    title: str = "Professor fired for speech",
    summary: str | None = "A professor was terminated.",
    severity: str | None = "medium",
    metadata: dict | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.source_id = source_id
    event.title = title
    event.summary = summary
    event.severity = severity
    event.nlp_summary = None
    event.nlp_relevance = "relevant"
    if metadata is None:
        metadata = {
            "lead_type": "incident",
            "institution": "UC Berkeley",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech"],
            "affected_person": "Dr. Smith",
        }
    event.metadata_ = metadata
    return event


def _make_lead(
    *,
    fingerprint: str = "abc123",
    event_ids: list | None = None,
    constitutional_basis: list | None = None,
    severity: str | None = "low",
    confidence: float = 0.5,
) -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.dedupe_fingerprint = fingerprint
    lead.event_ids = event_ids or [uuid.uuid4()]
    lead.constitutional_basis = constitutional_basis or ["1A-free-speech"]
    lead.severity = severity
    lead.confidence = confidence
    lead.last_updated_at = datetime.now(UTC)
    return lead


def _mock_db(existing_lead=None):
    db = AsyncMock()
    # First call returns the lead lookup result; subsequent calls return
    # empty event source_id results (for _collect_source_ids queries).
    lead_result = MagicMock()
    lead_result.scalar_one_or_none.return_value = existing_lead
    source_result = MagicMock()
    source_result.all.return_value = []
    db.execute = AsyncMock(side_effect=[lead_result, source_result])
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


class TestFingerprinting:
    def test_consistent_incident_fingerprint(self):
        fp1 = compute_incident_fingerprint("UC Berkeley", "Dr. Smith")
        fp2 = compute_incident_fingerprint("UC Berkeley", "Dr. Smith")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = compute_incident_fingerprint("UC BERKELEY", "DR. SMITH")
        fp2 = compute_incident_fingerprint("uc berkeley", "dr. smith")
        assert fp1 == fp2

    def test_whitespace_normalized(self):
        fp1 = compute_incident_fingerprint("  UC Berkeley  ", " Dr. Smith ")
        fp2 = compute_incident_fingerprint("UC Berkeley", "Dr. Smith")
        assert fp1 == fp2

    def test_different_inputs_different_fingerprints(self):
        fp1 = compute_incident_fingerprint("UC Berkeley", "Dr. Smith")
        fp2 = compute_incident_fingerprint("UCLA", "Dr. Jones")
        assert fp1 != fp2

    def test_policy_fingerprint_differs_from_incident(self):
        fp_inc = compute_incident_fingerprint("UC Berkeley", "speech code")
        fp_pol = compute_policy_fingerprint("UC Berkeley", "speech code")
        assert fp_inc != fp_pol

    def test_compute_fingerprint_dispatch(self):
        fp_inc = compute_fingerprint("incident", "UCLA", "key")
        fp_pol = compute_fingerprint("policy", "UCLA", "key")
        assert fp_inc == compute_incident_fingerprint("UCLA", "key")
        assert fp_pol == compute_policy_fingerprint("UCLA", "key")


# ---------------------------------------------------------------------------
# Confidence scoring tests
# ---------------------------------------------------------------------------


class TestConfidenceScoring:
    def test_single_source_baseline(self):
        score = compute_confidence(
            source_count=1,
            source_types={"rss"},
            severity="medium",
            entity_completeness=0.5,
        )
        assert 0.0 < score < 1.0

    def test_more_sources_increases_confidence(self):
        s1 = compute_confidence(1, {"rss"}, "medium", 0.5)
        s3 = compute_confidence(3, {"rss"}, "medium", 0.5)
        assert s3 > s1

    def test_cross_source_corroboration_bonus(self):
        single_type = compute_confidence(2, {"rss"}, "medium", 0.5)
        multi_type = compute_confidence(2, {"rss", "xai_x_search"}, "medium", 0.5)
        assert multi_type > single_type

    def test_higher_severity_increases_confidence(self):
        low = compute_confidence(1, {"rss"}, "low", 0.5)
        high = compute_confidence(1, {"rss"}, "high", 0.5)
        assert high > low

    def test_entity_completeness_impact(self):
        low_ent = compute_confidence(1, {"rss"}, "medium", 0.0)
        high_ent = compute_confidence(1, {"rss"}, "medium", 1.0)
        assert high_ent > low_ent

    def test_confidence_capped_at_1(self):
        score = compute_confidence(
            source_count=10,
            source_types={"rss", "xai_x_search", "university_policy"},
            severity="critical",
            entity_completeness=1.0,
            source_reputation={"rss_fire": 0.9},
            source_ids=["rss_fire"],
        )
        assert score <= 1.0

    def test_confidence_never_negative(self):
        score = compute_confidence(0, set(), None, 0.0)
        assert score >= 0.0

    def test_source_reputation_bonus(self):
        without_rep = compute_confidence(1, {"rss"}, "medium", 0.5)
        with_rep = compute_confidence(
            1, {"rss"}, "medium", 0.5,
            source_reputation={"rss_fire": 0.9},
            source_ids=["rss_fire"],
        )
        assert with_rep > without_rep


# ---------------------------------------------------------------------------
# Entity completeness tests
# ---------------------------------------------------------------------------


class TestEntityCompleteness:
    def test_fully_enriched_event(self):
        event = _make_event(metadata={
            "institution": "UCLA",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech"],
            "lead_type": "incident",
        })
        assert _entity_completeness(event) == pytest.approx(1.0)

    def test_empty_metadata(self):
        event = _make_event(metadata={})
        assert _entity_completeness(event) == pytest.approx(0.0)

    def test_partial_metadata(self):
        event = _make_event(metadata={"institution": "UCLA"})
        assert _entity_completeness(event) == pytest.approx(0.3)

    def test_invalid_constitutional_basis_not_counted(self):
        event = _make_event(metadata={
            "institution": "UCLA",
            "constitutional_basis": ["BOGUS-LABEL"],
        })
        # institution=0.3, invalid basis=0.0 -> 0.3
        assert _entity_completeness(event) == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Source type inference tests
# ---------------------------------------------------------------------------


class TestSeverityNormalization:
    def test_valid_severity(self):
        assert _normalize_severity("high") == "high"

    def test_none_severity(self):
        assert _normalize_severity(None) is None

    def test_invalid_severity_returns_none(self):
        assert _normalize_severity("UNKNOWN") is None

    def test_whitespace_stripped(self):
        assert _normalize_severity("  medium  ") == "medium"

    def test_case_normalized(self):
        assert _normalize_severity("HIGH") == "high"


class TestSourceType:
    def test_xai_source(self):
        assert _source_type("x_cal_california") == "xai_x_search"

    def test_rss_source(self):
        assert _source_type("rss_fire") == "rss"

    def test_university_source(self):
        assert _source_type("univ_uc_policy") == "university_policy"

    def test_unknown_source(self):
        assert _source_type("other_thing") == "unknown"


# ---------------------------------------------------------------------------
# LeadMatcher.match_event_to_lead tests
# ---------------------------------------------------------------------------


class TestMatchEventToLead:
    @pytest.fixture()
    def config(self):
        return LeadMatcherConfig(
            plan_id="cal-prospecting",
            confidence_threshold=0.3,
            source_reputation={"rss_fire": 0.9, "x_cal_california": 0.4},
        )

    @pytest.fixture()
    def matcher(self, config):
        return LeadMatcher(config)

    @pytest.mark.asyncio()
    async def test_creates_new_lead(self, matcher):
        event = _make_event()
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)

        assert lead is not None
        db.add.assert_called_once()
        assert lead.lead_type == "incident"
        assert lead.institution == "UC Berkeley"
        assert lead.jurisdiction == "CA"
        assert lead.plan_id == "cal-prospecting"
        assert event.id in lead.event_ids

    @pytest.mark.asyncio()
    async def test_updates_existing_lead(self, matcher):
        event = _make_event()
        existing = _make_lead(
            fingerprint=compute_fingerprint(
                "incident", "UC Berkeley", "Dr. Smith",
                plan_id="cal-prospecting",
            ),
        )
        db = _mock_db(existing_lead=existing)

        lead = await matcher.match_event_to_lead(event, db)

        assert lead is existing
        db.add.assert_not_called()

    @pytest.mark.asyncio()
    async def test_below_threshold_returns_none(self, matcher):
        matcher.config.confidence_threshold = 0.99
        event = _make_event(severity="info", metadata={
            "lead_type": "incident",
            "institution": "Unknown",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is None

    @pytest.mark.asyncio()
    async def test_filters_invalid_constitutional_basis(self, matcher):
        event = _make_event(metadata={
            "lead_type": "incident",
            "institution": "UCLA",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech", "INVALID-LABEL"],
            "affected_person": "Jane",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is not None
        assert "INVALID-LABEL" not in lead.constitutional_basis
        assert "1A-free-speech" in lead.constitutional_basis

    @pytest.mark.asyncio()
    async def test_policy_lead_type(self, matcher):
        event = _make_event(metadata={
            "lead_type": "policy",
            "institution": "Texas A&M",
            "jurisdiction": "TX",
            "constitutional_basis": ["1A-free-speech"],
            "policy_name": "DEI Compliance Policy",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is not None
        assert lead.lead_type == "policy"

    @pytest.mark.asyncio()
    async def test_update_merges_constitutional_basis(self, matcher):
        event = _make_event(metadata={
            "lead_type": "incident",
            "institution": "UC Berkeley",
            "jurisdiction": "CA",
            "constitutional_basis": ["14A-due-process"],
            "affected_person": "Dr. Smith",
        })
        existing = _make_lead(
            fingerprint=compute_fingerprint(
                "incident", "UC Berkeley", "Dr. Smith",
                plan_id="cal-prospecting",
            ),
            constitutional_basis=["1A-free-speech"],
        )
        db = _mock_db(existing_lead=existing)

        lead = await matcher.match_event_to_lead(event, db)
        # set_committed_value should have been called for merged basis
        assert lead is existing

    @pytest.mark.asyncio()
    async def test_update_bumps_severity(self, matcher):
        event = _make_event(severity="high")
        existing = _make_lead(
            fingerprint=compute_fingerprint(
                "incident", "UC Berkeley", "Dr. Smith",
                plan_id="cal-prospecting",
            ),
            severity="low",
        )
        db = _mock_db(existing_lead=existing)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead.severity == "high"

    @pytest.mark.asyncio()
    async def test_fallback_institution_to_source_id(self, matcher):
        event = _make_event(metadata={
            "lead_type": "incident",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is not None
        assert lead.institution == "rss_fire"

    @pytest.mark.asyncio()
    async def test_multiple_constitutional_bases(self, matcher):
        event = _make_event(metadata={
            "lead_type": "incident",
            "institution": "UCLA",
            "jurisdiction": "CA",
            "constitutional_basis": ["1A-free-speech", "14A-due-process", "1A-religion"],
            "affected_person": "Prof. Jones",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is not None
        assert len(lead.constitutional_basis) == 3

    @pytest.mark.asyncio()
    async def test_ambiguous_jurisdiction(self, matcher):
        event = _make_event(metadata={
            "lead_type": "incident",
            "institution": "Online University",
            "constitutional_basis": ["1A-free-speech"],
            "affected_person": "Student X",
        })
        db = _mock_db(existing_lead=None)

        lead = await matcher.match_event_to_lead(event, db)
        assert lead is not None
        assert lead.jurisdiction is None
