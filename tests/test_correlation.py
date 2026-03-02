"""Tests for correlation engine — exact indicator matching and semantic dedup."""

from osint_core.services.correlation import (
    correlate_exact,
    find_correlated_events,
    is_semantic_duplicate,
)

# ---- correlate_exact tests ---------------------------------------------------


def test_exact_match_same_cve():
    event_indicators = [{"type": "cve", "value": "CVE-2026-0001"}]
    existing_indicators = [{"type": "cve", "value": "CVE-2026-0001"}]
    assert correlate_exact(event_indicators, existing_indicators) is True


def test_no_exact_match():
    event_indicators = [{"type": "cve", "value": "CVE-2026-0001"}]
    existing_indicators = [{"type": "cve", "value": "CVE-2026-0002"}]
    assert correlate_exact(event_indicators, existing_indicators) is False


def test_exact_match_same_ip():
    event_indicators = [{"type": "ip", "value": "192.168.1.100"}]
    existing_indicators = [{"type": "ip", "value": "192.168.1.100"}]
    assert correlate_exact(event_indicators, existing_indicators) is True


def test_exact_match_same_domain():
    event_indicators = [{"type": "domain", "value": "evil.example.com"}]
    existing_indicators = [{"type": "domain", "value": "evil.example.com"}]
    assert correlate_exact(event_indicators, existing_indicators) is True


def test_exact_match_same_hash():
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    event_indicators = [{"type": "hash", "value": sha}]
    existing_indicators = [{"type": "hash", "value": sha}]
    assert correlate_exact(event_indicators, existing_indicators) is True


def test_exact_match_different_types():
    """Indicators with same value but different types should not match."""
    event_indicators = [{"type": "cve", "value": "192.168.1.1"}]
    existing_indicators = [{"type": "ip", "value": "192.168.1.1"}]
    assert correlate_exact(event_indicators, existing_indicators) is False


def test_exact_match_empty_indicators():
    assert correlate_exact([], []) is False
    assert correlate_exact([{"type": "cve", "value": "CVE-2026-0001"}], []) is False
    assert correlate_exact([], [{"type": "cve", "value": "CVE-2026-0001"}]) is False


def test_exact_match_multiple_indicators():
    """Match when at least one indicator overlaps."""
    event_indicators = [
        {"type": "cve", "value": "CVE-2026-0001"},
        {"type": "ip", "value": "10.0.0.1"},
    ]
    existing_indicators = [
        {"type": "cve", "value": "CVE-2026-0099"},
        {"type": "ip", "value": "10.0.0.1"},
    ]
    assert correlate_exact(event_indicators, existing_indicators) is True


# ---- is_semantic_duplicate tests ---------------------------------------------


def test_semantic_duplicate_detection():
    assert is_semantic_duplicate(similarity_score=0.92) is True
    assert is_semantic_duplicate(similarity_score=0.70) is False


def test_semantic_duplicate_at_threshold():
    """Score exactly at the threshold (0.85) should be considered a duplicate."""
    assert is_semantic_duplicate(similarity_score=0.85) is True


def test_semantic_duplicate_below_threshold():
    assert is_semantic_duplicate(similarity_score=0.84) is False


def test_semantic_duplicate_custom_threshold():
    assert is_semantic_duplicate(similarity_score=0.75, threshold=0.7) is True
    assert is_semantic_duplicate(similarity_score=0.65, threshold=0.7) is False


# ---- find_correlated_events tests -------------------------------------------


def test_find_correlated_events_combines_results():
    """find_correlated_events should combine exact and semantic matches."""
    event_indicators = [{"type": "cve", "value": "CVE-2026-0001"}]
    existing_events = [
        {
            "event_id": "evt-001",
            "indicators": [{"type": "cve", "value": "CVE-2026-0001"}],
            "similarity_score": 0.60,
        },
        {
            "event_id": "evt-002",
            "indicators": [{"type": "cve", "value": "CVE-2026-9999"}],
            "similarity_score": 0.92,
        },
        {
            "event_id": "evt-003",
            "indicators": [{"type": "ip", "value": "10.0.0.1"}],
            "similarity_score": 0.40,
        },
    ]

    results = find_correlated_events(event_indicators, existing_events)

    # evt-001: exact match (CVE overlap) -> included
    # evt-002: semantic duplicate (0.92 > 0.85) -> included
    # evt-003: no exact match, low similarity -> excluded
    result_ids = {r["event_id"] for r in results}
    assert "evt-001" in result_ids
    assert "evt-002" in result_ids
    assert "evt-003" not in result_ids


def test_find_correlated_events_no_matches():
    event_indicators = [{"type": "cve", "value": "CVE-2026-0001"}]
    existing_events = [
        {
            "event_id": "evt-001",
            "indicators": [{"type": "cve", "value": "CVE-2026-9999"}],
            "similarity_score": 0.30,
        },
    ]
    results = find_correlated_events(event_indicators, existing_events)
    assert results == []


def test_find_correlated_events_empty_input():
    assert find_correlated_events([], []) == []
