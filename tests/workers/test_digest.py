"""Tests for the Celery digest compilation worker task."""

from __future__ import annotations

import pytest

from osint_core.workers.digest import (
    _build_severity_breakdown,
    _build_source_breakdown,
    _window_hours,
    compile_digest,
)

# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_compile_digest_task_registered():
    """The compile_digest task should be registered with the correct name."""
    assert compile_digest.name == "osint.compile_digest"


def test_compile_digest_task_max_retries():
    """The compile_digest task should have max_retries=3."""
    assert compile_digest.max_retries == 3


def test_compile_digest_is_bound():
    """The compile_digest task should be a bound task (bind=True)."""
    assert compile_digest.__bound__ is True


# ---------------------------------------------------------------------------
# _window_hours helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "hours", "expected"),
    [
        ("daily", None, 24),
        ("weekly", None, 168),
        ("shift", None, 8),
        ("daily", 12, 12),
        ("unknown", None, 24),
        ("daily", 0, 24),  # zero treated as "not provided"
    ],
)
def test_window_hours(period: str, hours: int | None, expected: int) -> None:
    assert _window_hours(period, hours) == expected


# ---------------------------------------------------------------------------
# _build_severity_breakdown helper
# ---------------------------------------------------------------------------


def test_severity_breakdown_empty():
    assert _build_severity_breakdown([]) == {}


def test_severity_breakdown_single_severity():
    events = [{"severity": "high"}, {"severity": "high"}]
    assert _build_severity_breakdown(events) == {"high": 2}


def test_severity_breakdown_mixed():
    events = [
        {"severity": "critical"},
        {"severity": "high"},
        {"severity": "critical"},
        {"severity": "low"},
        {},  # missing severity defaults to "info"
    ]
    result = _build_severity_breakdown(events)
    assert result["critical"] == 2
    assert result["high"] == 1
    assert result["low"] == 1
    assert result["info"] == 1


def test_severity_breakdown_none_severity():
    events = [{"severity": None}]
    assert _build_severity_breakdown(events) == {"info": 1}


# ---------------------------------------------------------------------------
# _build_source_breakdown helper
# ---------------------------------------------------------------------------


def test_source_breakdown_empty():
    assert _build_source_breakdown([]) == {}


def test_source_breakdown_mixed():
    events = [
        {"source_id": "nvd"},
        {"source_id": "rss:bbc"},
        {"source_id": "nvd"},
        {},  # missing source_id → "unknown"
    ]
    result = _build_source_breakdown(events)
    assert result["nvd"] == 2
    assert result["rss:bbc"] == 1
    assert result["unknown"] == 1


# ---------------------------------------------------------------------------
# compile_digest task execution (stub path)
# ---------------------------------------------------------------------------


def _run_task(task_fn, *args, **kwargs):
    """Execute a bound Celery task directly via apply()."""
    return task_fn.apply(args=args, kwargs=kwargs).get()


def test_compile_digest_returns_empty_when_no_events():
    result = _run_task(compile_digest, "plan-abc")
    assert result["status"] == "empty"
    assert result["alert_count"] == 0
    assert result["plan_id"] == "plan-abc"
    assert result["period"] == "daily"
    assert result["window_hours"] == 24
    assert "window_start" in result
    assert "window_end" in result
    assert result["severity_breakdown"] == {}
    assert result["source_breakdown"] == {}
    assert result["digest_id"] is None


def test_compile_digest_period_weekly():
    result = _run_task(compile_digest, "plan-xyz", "weekly")
    assert result["window_hours"] == 168


def test_compile_digest_explicit_hours():
    result = _run_task(compile_digest, "plan-xyz", "daily", 48)
    assert result["window_hours"] == 48


def test_compile_digest_window_timestamps_are_iso8601():
    result = _run_task(compile_digest, "plan-abc")
    from datetime import datetime

    # Should not raise
    datetime.fromisoformat(result["window_start"])
    datetime.fromisoformat(result["window_end"])
