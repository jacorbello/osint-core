"""Tests for Celery scoring tasks."""

from osint_core.workers.score import rescore_all_events_task, score_event_task


def test_score_event_task_registered():
    """score_event_task should be registered with the correct name."""
    assert score_event_task.name == "osint.score_event"


def test_score_event_task_max_retries():
    assert score_event_task.max_retries == 3


def test_score_event_task_is_bound():
    assert score_event_task.__bound__ is True


def test_rescore_all_events_task_registered():
    """rescore_all_events_task should be registered with the correct name."""
    assert rescore_all_events_task.name == "osint.rescore_all_events"
