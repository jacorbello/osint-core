"""Scoring engine — compute event relevance scores.

Score formula:
    score = base_reputation * recency_decay * ioc_multiplier * topic_relevance

Where:
    - base_reputation = source_reputation.get(source_id, 1.0)
    - recency_decay = 0.5 ^ (hours_old / half_life_hours)
    - ioc_multiplier = ioc_match_boost if indicator_count > 0, else 1.0
    - topic_relevance = keyword_miss_penalty if 0 matches, else min(1.0 + 0.2 * n, 3.0)

Severity mapping:
    [0, 1)     -> low
    [1, 3)     -> medium
    [3, 7)     -> high
    [7, +inf)  -> critical
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class ScoringConfig:
    """Configuration for the scoring engine."""

    recency_half_life_hours: float
    source_reputation: dict[str, float] = field(default_factory=dict)
    ioc_match_boost: float = 1.0
    topic_relevance_multiplier: float = 1.0
    keyword_miss_penalty: float = 0.1
    keywords: list[str] = field(default_factory=list)


@dataclass
class ReliabilityProfile:
    """NATO-style source reliability metadata."""

    reliability: str = "C"  # A through F
    credibility: int = 3    # 1 (confirmed) through 6 (truth cannot be judged)
    corroboration_required: bool = False


RELIABILITY_FACTORS: dict[str, float] = {
    "A": 1.5,
    "B": 1.2,
    "C": 1.0,
    "D": 0.7,
    "E": 0.5,
    "F": 0.3,
}

CORROBORATION_BONUS = 1.5


def reliability_factor(grade: str) -> float:
    """Convert a NATO reliability grade to a scoring multiplier."""
    return RELIABILITY_FACTORS.get(grade.upper(), 1.0)


def compute_topic_relevance(matched_topics: list[str], config: ScoringConfig) -> float:
    """Compute the topic relevance multiplier.

    - No keywords configured: return 1.0 (backward compatible, no penalty).
    - 0 matches: return keyword_miss_penalty.
    - n matches: return min(1.0 + 0.2 * n, 3.0).
    """
    if not config.keywords:
        return 1.0
    n = len(matched_topics)
    if n == 0:
        return config.keyword_miss_penalty
    return min(1.0 + 0.2 * n, 3.0)


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return the subset of keywords found (case-insensitive) in text."""
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def score_event(
    source_id: str,
    occurred_at: datetime,
    indicator_count: int,
    matched_topics: list[str],
    config: ScoringConfig,
) -> float:
    """Compute a relevance score for an event.

    Args:
        source_id: The identifier of the source that produced this event.
        occurred_at: When the event occurred (timezone-aware).
        indicator_count: Number of IOC indicators linked to this event.
        matched_topics: List of matched topic keywords.
        config: Scoring configuration parameters.

    Returns:
        A non-negative float score.
    """
    base = config.source_reputation.get(source_id, 1.0)

    now = datetime.now(UTC)
    hours_old = max((now - occurred_at).total_seconds() / 3600.0, 0.0)
    decay = math.pow(0.5, hours_old / config.recency_half_life_hours)

    ioc_multiplier = config.ioc_match_boost if indicator_count > 0 else 1.0

    topic_relevance = compute_topic_relevance(matched_topics, config)

    return base * decay * ioc_multiplier * topic_relevance


def score_to_severity(score: float) -> str:
    """Map a numeric score to a severity label.

    Ranges:
        [0, 1)     -> low
        [1, 3)     -> medium
        [3, 7)     -> high
        [7, +inf)  -> critical
    """
    if score < 1.0:
        return "low"
    if score < 3.0:
        return "medium"
    if score < 7.0:
        return "high"
    return "critical"


def score_event_v2(
    source_id: str,
    occurred_at: datetime,
    indicator_count: int,
    matched_topics: list[str],
    config: ScoringConfig,
    reliability_profile: ReliabilityProfile | None = None,
    corroborated: bool = False,
) -> float:
    """Extended scoring with reliability weighting and corroboration bonus.

    Formula:
        score = base_reputation * reliability_factor * recency_decay
               * ioc_multiplier * topic_relevance * corroboration_bonus
    """
    base_score = score_event(source_id, occurred_at, indicator_count, matched_topics, config)

    rel_factor = 1.0
    if reliability_profile:
        rel_factor = reliability_factor(reliability_profile.reliability)

    corr_bonus = CORROBORATION_BONUS if corroborated else 1.0

    return base_score * rel_factor * corr_bonus
