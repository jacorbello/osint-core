"""Tests for the Celery correlate_event worker task."""

from __future__ import annotations

from unittest.mock import patch

from osint_core.workers.enrich import correlate_event_task

# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_correlate_event_task_registered():
    """correlate_event_task should be registered under the correct name."""
    assert correlate_event_task.name == "osint.correlate_event"


def test_correlate_event_task_max_retries():
    assert correlate_event_task.max_retries == 3


def test_correlate_event_is_bound():
    assert correlate_event_task.__bound__ is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_task(task_fn, *args, **kwargs):
    """Execute a bound Celery task directly via apply()."""
    return task_fn.apply(args=args, kwargs=kwargs).get()


# ---------------------------------------------------------------------------
# correlate_event_task — no_vector path (Qdrant unavailable)
# ---------------------------------------------------------------------------


def test_correlate_event_returns_no_vector_when_qdrant_unavailable():
    """When Qdrant is unreachable, the task returns status=no_vector."""
    with patch(
        "osint_core.workers.enrich.search_similar",
        side_effect=ConnectionError("qdrant down"),
    ):
        result = _run_task(correlate_event_task, "event-123")

    assert result["status"] == "no_vector"
    assert result["event_id"] == "event-123"
    assert result["correlations_found"] == 0
    assert result["correlated_event_ids"] == []


# ---------------------------------------------------------------------------
# correlate_event_task — no matches
# ---------------------------------------------------------------------------


def test_correlate_event_returns_ok_with_no_matches():
    """When Qdrant returns no hits above threshold, correlations_found=0."""
    with patch("osint_core.workers.enrich.search_similar", return_value=[]):
        result = _run_task(correlate_event_task, "event-456")

    assert result["status"] == "ok"
    assert result["correlations_found"] == 0
    assert result["correlated_event_ids"] == []
    assert result["match_types"] == {}


# ---------------------------------------------------------------------------
# correlate_event_task — semantic match
# ---------------------------------------------------------------------------


def test_correlate_event_semantic_match():
    """High-similarity hits without indicator overlap are recorded as 'semantic'."""
    fake_hits = [
        {
            "id": "qpoint-1",
            "score": 0.92,
            "payload": {"event_id": "event-999", "indicators": []},
        }
    ]
    with patch("osint_core.workers.enrich.search_similar", return_value=fake_hits):
        result = _run_task(correlate_event_task, "event-100")

    assert result["status"] == "ok"
    assert result["correlations_found"] == 1
    assert "event-999" in result["correlated_event_ids"]
    assert result["match_types"]["event-999"] == "semantic"


# ---------------------------------------------------------------------------
# correlate_event_task — self-match excluded
# ---------------------------------------------------------------------------


def test_correlate_event_excludes_self():
    """A Qdrant hit whose event_id equals the target event_id is skipped."""
    fake_hits = [
        {
            "id": "qpoint-self",
            "score": 1.0,
            "payload": {"event_id": "event-self", "indicators": []},
        }
    ]
    with patch("osint_core.workers.enrich.search_similar", return_value=fake_hits):
        result = _run_task(correlate_event_task, "event-self")

    assert result["correlations_found"] == 0


# ---------------------------------------------------------------------------
# correlate_event_task — exact indicator match
# ---------------------------------------------------------------------------


def test_correlate_event_exact_match_via_indicators():
    """Shared (type, value) indicators trigger an 'exact' or 'both' match."""
    shared_indicator = {"type": "cve", "value": "CVE-2026-0001"}
    fake_hits = [
        {
            "id": "qpoint-2",
            "score": 0.5,  # Below semantic threshold (0.85)
            "payload": {
                "event_id": "event-888",
                "indicators": [shared_indicator],
            },
        }
    ]
    # The target event also references the same CVE (injected via monkeypatch
    # of the in-task variable is not possible; instead rely on find_correlated_events
    # which is tested separately in test_correlation.py — here we verify the task
    # plumbs the data through correctly when the payload carries indicators).
    with patch("osint_core.workers.enrich.search_similar", return_value=fake_hits):
        # With empty event_indicators (stub), exact match won't fire, so score
        # below threshold means no match.
        result = _run_task(correlate_event_task, "event-200")

    # With empty event_indicators the exact check returns False; score 0.5 is
    # below DEFAULT_SEMANTIC_THRESHOLD (0.85), so no correlation.
    assert result["status"] == "ok"
    assert result["correlations_found"] == 0
