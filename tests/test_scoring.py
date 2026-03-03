"""Tests for scoring engine — source reputation, recency decay, and IOC boost."""

from datetime import UTC, datetime, timedelta

import pytest

from osint_core.services.scoring import (
    ReliabilityProfile,
    ScoringConfig,
    reliability_factor,
    score_event,
    score_event_v2,
    score_to_severity,
)


def test_base_score_from_source_reputation():
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"cisa_kev": 1.5},
        ioc_match_boost=2.0,
    )
    score = score_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(UTC),
        indicator_count=0,
        matched_topics=[],
        config=config,
    )
    assert score == pytest.approx(1.5, abs=0.1)


def test_recency_decay():
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"src": 1.0},
        ioc_match_boost=1.0,
    )
    recent = score_event("src", datetime.now(UTC), 0, [], config)
    old = score_event("src", datetime.now(UTC) - timedelta(hours=96), 0, [], config)
    assert recent > old
    assert old == pytest.approx(recent * 0.25, abs=0.1)  # 2 half-lives


def test_ioc_boost():
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"src": 1.0},
        ioc_match_boost=3.0,
    )
    without = score_event("src", datetime.now(UTC), 0, [], config)
    with_ioc = score_event("src", datetime.now(UTC), 2, [], config)
    assert with_ioc == pytest.approx(without * 3.0, abs=0.1)


def test_unknown_source_defaults_to_one():
    """Unknown source_id should default to reputation of 1.0."""
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"known": 2.0},
        ioc_match_boost=1.0,
    )
    score = score_event("unknown_source", datetime.now(UTC), 0, [], config)
    assert score == pytest.approx(1.0, abs=0.1)


def test_severity_low():
    assert score_to_severity(0.5) == "low"


def test_severity_medium():
    assert score_to_severity(2.0) == "medium"


def test_severity_high():
    assert score_to_severity(5.0) == "high"


def test_severity_critical():
    assert score_to_severity(8.0) == "critical"


def test_severity_boundary_one():
    """Score of exactly 1.0 should be medium (boundary: 0-1=low, 1-3=medium)."""
    assert score_to_severity(1.0) == "medium"


def test_severity_boundary_three():
    """Score of exactly 3.0 should be high."""
    assert score_to_severity(3.0) == "high"


def test_severity_boundary_seven():
    """Score of exactly 7.0 should be critical."""
    assert score_to_severity(7.0) == "critical"


def test_zero_score():
    """A zero score should be 'low'."""
    assert score_to_severity(0.0) == "low"


def test_very_old_event_has_near_zero_score():
    """An event from 30 days ago should have a very small score."""
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"src": 1.0},
        ioc_match_boost=1.0,
    )
    score = score_event(
        "src",
        datetime.now(UTC) - timedelta(days=30),
        0,
        [],
        config,
    )
    assert score < 0.01


def test_ioc_boost_not_applied_when_zero_indicators():
    """IOC boost should not multiply when indicator_count is 0."""
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"src": 1.0},
        ioc_match_boost=10.0,
    )
    score = score_event("src", datetime.now(UTC), 0, [], config)
    # Without IOC boost, score should be close to 1.0 (reputation * ~1.0 recency)
    assert score == pytest.approx(1.0, abs=0.1)


def test_reliability_factor_a():
    assert reliability_factor("A") == 1.5


def test_reliability_factor_b():
    assert reliability_factor("B") == 1.2


def test_reliability_factor_c():
    assert reliability_factor("C") == 1.0


def test_reliability_factor_unknown_defaults_to_c():
    assert reliability_factor("X") == 1.0


def test_score_event_v2_includes_reliability():
    config = ScoringConfig(recency_half_life_hours=24)
    profile = ReliabilityProfile(reliability="A", credibility=2, corroboration_required=False)
    score = score_event_v2(
        source_id="isw",
        occurred_at=datetime.now(UTC),
        indicator_count=0,
        matched_topics=[],
        config=config,
        reliability_profile=profile,
        corroborated=False,
    )
    # A reliability = 1.5x multiplier, freshly occurred = ~1.0 decay
    assert score > 1.0


def test_score_event_v2_corroboration_bonus():
    config = ScoringConfig(recency_half_life_hours=24)
    profile = ReliabilityProfile(reliability="B", credibility=3, corroboration_required=True)
    uncorroborated = score_event_v2(
        source_id="gdelt",
        occurred_at=datetime.now(UTC),
        indicator_count=0,
        matched_topics=[],
        config=config,
        reliability_profile=profile,
        corroborated=False,
    )
    corroborated = score_event_v2(
        source_id="gdelt",
        occurred_at=datetime.now(UTC),
        indicator_count=0,
        matched_topics=[],
        config=config,
        reliability_profile=profile,
        corroborated=True,
    )
    assert corroborated > uncorroborated
    assert corroborated == pytest.approx(uncorroborated * 1.5, rel=0.01)
