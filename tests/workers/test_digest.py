"""Tests for the Celery digest compilation worker task."""

from osint_core.workers.digest import compile_digest


def test_compile_digest_task_registered():
    """The compile_digest task should be registered with the correct name."""
    assert compile_digest.name == "osint.compile_digest"


def test_compile_digest_task_max_retries():
    """The compile_digest task should have max_retries=3."""
    assert compile_digest.max_retries == 3


def test_compile_digest_is_bound():
    """The compile_digest task should be a bound task (bind=True)."""
    assert compile_digest.__bound__ is True
