"""Scoring engine — compute event relevance scores.

Score formula:
    score = base_reputation * recency_decay * ioc_multiplier

Where:
    - base_reputation = source_reputation.get(source_id, 1.0)
    - recency_decay = 0.5 ^ (hours_old / half_life_hours)
    - ioc_multiplier = ioc_match_boost if indicator_count > 0, else 1.0

Severity mapping:
    [0, 1)     -> low
    [1, 3)     -> medium
    [3, 7)     -> high
    [7, +inf)  -> critical
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScoringConfig:
    """Configuration for the scoring engine."""

    recency_half_life_hours: float
    source_reputation: dict[str, float] = field(default_factory=dict)
    ioc_match_boost: float = 1.0


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
        matched_topics: List of matched topic tags (reserved for future use).
        config: Scoring configuration parameters.

    Returns:
        A non-negative float score.
    """
    # Base reputation (default 1.0 for unknown sources)
    base = config.source_reputation.get(source_id, 1.0)

    # Recency decay: 0.5^(hours_old / half_life)
    now = datetime.now(timezone.utc)
    hours_old = max((now - occurred_at).total_seconds() / 3600.0, 0.0)
    decay = math.pow(0.5, hours_old / config.recency_half_life_hours)

    # IOC boost: multiply by ioc_match_boost if any indicators present
    ioc_multiplier = config.ioc_match_boost if indicator_count > 0 else 1.0

    return base * decay * ioc_multiplier


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
