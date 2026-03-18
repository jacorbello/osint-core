"""Tests for the new normalized 0-1 scoring formula."""
from datetime import UTC, datetime, timedelta

import pytest

from osint_core.services.scoring import (
    ScoringConfig,
    compute_geographic_relevance,
    compute_keyword_relevance,
    score_event,
    score_to_severity,
)


def _now():
    return datetime.now(UTC)


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
            target_geo={
                "lat": 30.2672, "lon": -97.7431,
                "radius_km": 150, "country_codes": ["USA"],
            },
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
            matched_keywords=1,
            total_keywords=1,
            config=config,
            corroboration_count=5,
        )
        assert score <= 1.0


class TestEdgeCases:
    """Document and verify behavior when keywords/target_geo are missing."""

    def test_compute_keyword_relevance_no_keywords(self):
        """When total_keywords=0, keyword relevance is 1.0 regardless of content."""
        config = ScoringConfig(recency_half_life_hours=48, keywords=[])
        assert compute_keyword_relevance(0, 0, config) == 1.0

    def test_compute_keyword_relevance_no_matches(self):
        """When keywords exist but none match, penalty is applied."""
        config = ScoringConfig(recency_half_life_hours=48, keywords=["terrorism", "attack"])
        assert compute_keyword_relevance(0, 2, config) == 0.05

    def test_compute_keyword_relevance_partial_match(self):
        """Partial keyword match gives proportional score."""
        config = ScoringConfig(
            recency_half_life_hours=48, keywords=["terrorism", "attack", "bombing"],
        )
        assert compute_keyword_relevance(1, 3, config) == pytest.approx(1 / 3)

    def test_compute_keyword_relevance_nlp_override(self):
        """NLP relevance classification overrides keyword matching."""
        config = ScoringConfig(recency_half_life_hours=48, keywords=["terrorism"])
        assert compute_keyword_relevance(0, 1, config, nlp_relevance="relevant") == 1.0
        assert compute_keyword_relevance(1, 1, config, nlp_relevance="irrelevant") == 0.05
        assert compute_keyword_relevance(0, 1, config, nlp_relevance="tangential") == 0.4

    def test_compute_geographic_relevance_no_target_geo(self):
        """No target_geo means all events get 1.0 geographic relevance."""
        assert compute_geographic_relevance(None, None, None, None) == 1.0
        assert compute_geographic_relevance("USA", 30.27, -97.74, None) == 1.0

    def test_compute_geographic_relevance_with_target(self):
        """Events far from target get penalized."""
        target = {"country_codes": ["USA"], "lat": 30.2672, "lon": -97.7431, "radius_km": 100}
        # Austin, TX (within radius)
        assert compute_geographic_relevance("USA", 30.27, -97.74, target) == 1.0
        # New York (far from Austin, same country)
        assert compute_geographic_relevance("USA", 40.71, -74.01, target) == 0.5
        # London (different country)
        assert compute_geographic_relevance("GBR", 51.51, -0.13, target) == 0.2

    def test_score_event_empty_config_gives_high_score(self):
        """Demonstrates the scoring problem: empty keywords+geo = everything scores high."""
        from datetime import UTC, datetime

        config = ScoringConfig(recency_half_life_hours=48, source_reputation={"kxan_rss": 1.0})
        score = score_event(
            source_id="kxan_rss",
            occurred_at=datetime.now(UTC),
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        # With no keywords and no target_geo, score should be ~1.0 * 1.0 * 1.0 * ~1.0
        assert score > 0.9


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
