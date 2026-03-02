"""Correlation engine — exact indicator matching and semantic deduplication.

Supports two correlation strategies:

1. **Exact matching** — two events share at least one indicator with the same
   type and value (e.g., both reference CVE-2026-0001).
2. **Semantic deduplication** — the cosine similarity between two event
   embeddings exceeds a configurable threshold (default 0.85).

``find_correlated_events`` combines both strategies to produce a unified list
of correlated events.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Default cosine-similarity threshold above which two events are considered
# semantic duplicates.
DEFAULT_SEMANTIC_THRESHOLD = 0.85


def correlate_exact(
    event_indicators: list[dict],
    existing_indicators: list[dict],
) -> bool:
    """Check whether two indicator sets share at least one (type, value) pair.

    Args:
        event_indicators: Indicators from the event under evaluation.
            Each dict must have ``type`` and ``value`` keys.
        existing_indicators: Indicators from a candidate event.

    Returns:
        ``True`` if there is at least one overlapping indicator, ``False``
        otherwise.
    """
    if not event_indicators or not existing_indicators:
        return False

    event_set = {(ind["type"], ind["value"]) for ind in event_indicators}
    existing_set = {(ind["type"], ind["value"]) for ind in existing_indicators}

    return bool(event_set & existing_set)


def is_semantic_duplicate(
    similarity_score: float,
    threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> bool:
    """Determine whether a similarity score indicates a semantic duplicate.

    Args:
        similarity_score: Cosine similarity between two event embeddings
            (range 0.0 to 1.0).
        threshold: Minimum score to consider the pair duplicates.

    Returns:
        ``True`` when ``similarity_score >= threshold``.
    """
    return similarity_score >= threshold


def find_correlated_events(
    event_indicators: list[dict],
    existing_events: list[dict],
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> list[dict]:
    """Find events correlated to the current event via exact or semantic match.

    Each entry in *existing_events* is expected to have:
      - ``event_id``: str
      - ``indicators``: list[dict] with ``type`` / ``value`` keys
      - ``similarity_score``: float cosine similarity to the current event

    An existing event is considered correlated if:
      - **exact**: it shares at least one (type, value) indicator pair, OR
      - **semantic**: its ``similarity_score`` meets the threshold.

    Args:
        event_indicators: Indicators extracted from the event being evaluated.
        existing_events: Candidate events to check for correlation.
        semantic_threshold: Cosine similarity threshold for semantic matching.

    Returns:
        A list of dicts, each containing ``event_id``, ``match_type``
        (``"exact"``, ``"semantic"``, or ``"both"``), and ``score``.
    """
    results: list[dict] = []

    for candidate in existing_events:
        exact = correlate_exact(event_indicators, candidate.get("indicators", []))
        semantic = is_semantic_duplicate(
            candidate.get("similarity_score", 0.0),
            threshold=semantic_threshold,
        )

        if exact and semantic:
            match_type = "both"
        elif exact:
            match_type = "exact"
        elif semantic:
            match_type = "semantic"
        else:
            continue

        results.append(
            {
                "event_id": candidate["event_id"],
                "match_type": match_type,
                "score": candidate.get("similarity_score", 0.0),
            }
        )

    return results
