"""Tests for the new normalized 0-1 scoring formula."""
import pytest
from datetime import datetime, timezone, timedelta
from osint_core.services.scoring import (
    ScoringConfig,
    score_event,
    score_to_severity,
    compute_keyword_relevance,
    compute_geographic_relevance,
)


def _now():
    return datetime.now(timezone.utc)


class TestKeywordRelevance:
    def test_no_keywords_configured_returns_one(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=[])
        assert compute_keyword_relevance(0, 0, config) == 1.0

    def test_no_matches_returns_low_score(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["terror", "attack", "bomb"])
        assert compute_keyword_relevance(0, 3, config) == pytest.approx(0.05)

    def test_all_keywords_matched_returns_one(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["terror", "attack"])
        assert compute_keyword_relevance(2, 2, config) == pytest.approx(1.0)

    def test_partial_match(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b", "c", "d"])
        result = compute_keyword_relevance(2, 4, config)
        assert 0.0 < result < 1.0

    def test_nlp_relevant_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="relevant") == 1.0

    def test_nlp_tangential_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="tangential") == 0.4

    def test_nlp_irrelevant_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="irrelevant") == 0.05


class TestGeographicRelevance:
    def test_no_target_geo_returns_one(self):
        assert compute_geographic_relevance(None, None, None, target_geo=None) == 1.0

    def test_exact_country_match(self):
        result = compute_geographic_relevance(
            country_code="USA", lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 1.0

    def test_wrong_country(self):
        result = compute_geographic_relevance(
            country_code="CHN", lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 0.2

    def test_no_geo_data_benefit_of_doubt(self):
        result = compute_geographic_relevance(
            country_code=None, lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 0.7

    def test_within_radius(self):
        result = compute_geographic_relevance(
            country_code="USA", lat=30.27, lon=-97.74,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 50},
        )
        assert result == 1.0

    def test_within_2x_radius(self):
        result = compute_geographic_relevance(
            country_code="USA", lat=29.76, lon=-95.37,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 150},
        )
        assert result == 0.7

    def test_same_country_beyond_2x_radius(self):
        result = compute_geographic_relevance(
            country_code="USA", lat=40.71, lon=-74.01,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 150, "country_codes": ["USA"]},
        )
        assert result == 0.5


class TestScoreEvent:
    def test_fresh_relevant_event_scores_high(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=["terror", "attack"],
            source_reputation={"cisa_kev": 1.0},
        )
        score = score_event(
            source_id="cisa_kev",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=2,
            total_keywords=2,
            config=config,
        )
        assert 0.9 <= score <= 1.0

    def test_old_event_decays(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={"src": 1.0},
        )
        score = score_event(
            source_id="src",
            occurred_at=_now() - timedelta(hours=24),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        assert 0.2 <= score <= 0.3

    def test_decay_floor(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={"src": 1.0},
        )
        score = score_event(
            source_id="src",
            occurred_at=_now() - timedelta(hours=1000),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        assert score >= 0.1 * 0.5

    def test_unknown_source_defaults_half(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={},
        )
        score = score_event(
            source_id="unknown",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        assert 0.45 <= score <= 0.55

    def test_score_clamped_to_one(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=["a"],
            source_reputation={"src": 1.0},
        )
        score = score_event(
            source_id="src",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=1,
            total_keywords=1,
            config=config,
            corroboration_count=5,
        )
        assert score <= 1.0


class TestScoreToSeverity:
    def test_info(self):
        assert score_to_severity(0.1) == "info"

    def test_low(self):
        assert score_to_severity(0.3) == "low"

    def test_medium(self):
        assert score_to_severity(0.6) == "medium"

    def test_high(self):
        assert score_to_severity(0.8) == "high"

    def test_boundary_low_medium(self):
        assert score_to_severity(0.5) == "medium"

    def test_boundary_medium_high(self):
        assert score_to_severity(0.75) == "high"
