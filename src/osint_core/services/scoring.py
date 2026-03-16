"""Scoring engine for OSINT events.

Formula:
    relevance_score = keyword_relevance * geographic_relevance * source_trust
    recency_factor = max(0.1, 0.5^(hours_old / half_life))
    boosted = relevance_score * corroboration_bonus
    final_score = min(1.0, boosted * recency_factor)

Severity thresholds (from final_score):
    0.0-0.2  -> info
    0.2-0.5  -> low
    0.5-0.75 -> medium
    0.75-1.0 -> high
    (critical is signal-promoted only)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScoringConfig:
    recency_half_life_hours: float
    source_reputation: dict[str, float] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    keyword_miss_penalty: float = 0.05
    target_geo: dict | None = None


NLP_RELEVANCE_MAP: dict[str, float] = {
    "relevant": 1.0,
    "tangential": 0.4,
    "irrelevant": 0.05,
}


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Case-insensitive substring match of keywords against text."""
    if not text or not keywords:
        return []
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def compute_keyword_relevance(
    matched_count: int,
    total_keywords: int,
    config: ScoringConfig,
    nlp_relevance: str | None = None,
) -> float:
    """Compute keyword relevance factor (0.0-1.0).

    If NLP classification is available, it overrides keyword matching.
    """
    if nlp_relevance and nlp_relevance in NLP_RELEVANCE_MAP:
        return NLP_RELEVANCE_MAP[nlp_relevance]
    if total_keywords == 0:
        return 1.0
    if matched_count == 0:
        return config.keyword_miss_penalty
    return matched_count / total_keywords


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_geographic_relevance(
    country_code: str | None,
    lat: float | None,
    lon: float | None,
    target_geo: dict | None,
) -> float:
    """Compute geographic relevance factor (0.0-1.0)."""
    if target_geo is None:
        return 1.0

    target_countries = target_geo.get("country_codes", [])
    target_lat = target_geo.get("lat")
    target_lon = target_geo.get("lon")
    radius_km = target_geo.get("radius_km")

    # Lat/lon radius check takes precedence when available
    if (
        lat is not None
        and lon is not None
        and target_lat is not None
        and target_lon is not None
        and radius_km is not None
    ):
        dist = _haversine_km(lat, lon, target_lat, target_lon)
        if dist <= radius_km:
            return 1.0
        if dist <= radius_km * 2:
            return 0.7
        # Beyond 2x radius but same country
        if country_code and country_code in target_countries:
            return 0.5
        if country_code:
            return 0.2
        return 0.7  # no country info

    # Country-only check
    if not country_code and not lat:
        return 0.7  # benefit of doubt
    if country_code and target_countries and country_code in target_countries:
        return 1.0
    if country_code and target_countries:
        return 0.2

    return 0.7


def score_event(
    source_id: str,
    occurred_at: datetime | None,
    matched_keywords: int,
    total_keywords: int,
    config: ScoringConfig,
    *,
    country_code: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    nlp_relevance: str | None = None,
    corroboration_count: int = 0,
) -> float:
    """Score an event on a 0.0-1.0 scale."""
    source_trust = config.source_reputation.get(source_id, 0.5)

    keyword_rel = compute_keyword_relevance(
        matched_keywords, total_keywords, config, nlp_relevance=nlp_relevance,
    )

    geo_rel = compute_geographic_relevance(
        country_code, lat, lon, config.target_geo,
    )

    relevance = keyword_rel * geo_rel * source_trust

    # Corroboration bonus (capped at 1.5x)
    if corroboration_count > 0:
        bonus = min(1.5, 1.0 + 0.2 * corroboration_count)
        relevance *= bonus

    # Recency decay with floor
    if occurred_at is not None:
        now = datetime.now(timezone.utc)
        hours_old = max(0.0, (now - occurred_at).total_seconds() / 3600)
        recency = max(0.1, 0.5 ** (hours_old / config.recency_half_life_hours))
    else:
        recency = 0.5  # unknown time, middle ground

    return min(1.0, relevance * recency)


def score_to_severity(score: float) -> str:
    """Map a 0.0-1.0 score to severity label."""
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.2:
        return "low"
    return "info"
