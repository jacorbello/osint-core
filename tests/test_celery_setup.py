"""Tests for Celery application configuration."""

from osint_core.workers.celery_app import celery_app


def test_celery_app_configured():
    assert celery_app.main == "osint-core"
    assert "redis" in celery_app.conf.broker_url


def test_celery_queue_routing():
    routes = celery_app.conf.task_routes
    assert "osint_core.workers.ingest.*" in routes
    assert routes["osint_core.workers.ingest.*"]["queue"] == "ingest"


def test_celery_serializer_settings():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


def test_celery_reliability_settings():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_track_started is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_celery_default_queue():
    assert celery_app.conf.task_default_queue == "osint"


def test_celery_beat_schedule_empty():
    assert celery_app.conf.beat_schedule == {}
