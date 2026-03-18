"""Tests for event sort parameter parsing."""

from osint_core.api.routes.events import _parse_sort


def _clause_str(clause) -> str:
    """Render the ORDER BY clause to a string for assertion."""
    return str(clause).upper()


def test_sort_default_is_ingested_at_desc():
    """No sort param should default to ingested_at DESC."""
    clause_str = _clause_str(_parse_sort(None))
    assert "INGESTED_AT" in clause_str
    assert "DESC" in clause_str


def test_sort_minus_score_is_score_desc():
    """'-score' should produce score DESC (highest first)."""
    clause_str = _clause_str(_parse_sort("-score"))
    assert "SCORE" in clause_str
    assert "DESC" in clause_str


def test_sort_score_is_score_asc():
    """'score' (no prefix) should produce score ASC (lowest first)."""
    clause_str = _clause_str(_parse_sort("score"))
    assert "SCORE" in clause_str
    assert "ASC" in clause_str


def test_sort_ingested_at_desc():
    clause_str = _clause_str(_parse_sort("-ingested_at"))
    assert "INGESTED_AT" in clause_str
    assert "DESC" in clause_str


def test_sort_occurred_at_asc():
    clause_str = _clause_str(_parse_sort("occurred_at"))
    assert "OCCURRED_AT" in clause_str
    assert "ASC" in clause_str


def test_sort_unknown_field_falls_back_to_ingested_at_desc():
    """Unknown sort fields should fall back to default (ingested_at DESC)."""
    clause_str = _clause_str(_parse_sort("-nonexistent_field"))
    assert "INGESTED_AT" in clause_str
    assert "DESC" in clause_str
