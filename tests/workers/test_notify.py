"""Tests for the Celery notification worker task."""

from osint_core.workers.notify import send_notification


def test_send_notification_task_registered():
    """The send_notification task should be registered with the correct name."""
    assert send_notification.name == "osint.send_notification"


def test_send_notification_task_max_retries():
    """The send_notification task should have max_retries=3."""
    assert send_notification.max_retries == 3


def test_send_notification_is_bound():
    """The send_notification task should be a bound task (bind=True)."""
    assert send_notification.__bound__ is True
