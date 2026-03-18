"""Tests for Celery application configuration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.celery_app import celery_app, load_beat_schedule


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


def test_celery_beat_schedule_empty_at_import():
    """Beat schedule is empty at import time; populated by beat_init signal."""
    assert celery_app.conf.beat_schedule == {}


def test_load_beat_schedule_with_active_plan():
    """load_beat_schedule populates beat_schedule from active plans."""
    mock_plan = MagicMock()
    mock_plan.plan_id = "test-plan"
    mock_plan.version = 1
    mock_plan.content = {
        "plan_id": "test-plan",
        "sources": [
            {"id": "cisa_kev", "type": "cisa_kev", "schedule_cron": "0 */6 * * *"},
            {"id": "gdelt", "type": "gdelt_api", "schedule_cron": "*/15 * * * *"},
        ],
    }

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("osint_core.db.async_session", mock_session_factory),
        patch(
            "osint_core.services.plan_store.PlanStore.get_all_active",
            new_callable=AsyncMock,
            return_value=[mock_plan],
        ),
    ):
        load_beat_schedule()

    schedule = celery_app.conf.beat_schedule
    assert "ingest-test-plan-cisa_kev" in schedule
    assert "ingest-test-plan-gdelt" in schedule
    assert schedule["ingest-test-plan-cisa_kev"]["task"] == "osint.ingest_source"
    assert schedule["ingest-test-plan-cisa_kev"]["args"] == ["cisa_kev", "test-plan"]
    assert schedule["ingest-test-plan-cisa_kev"]["options"]["queue"] == "ingest"
    assert schedule["ingest-test-plan-gdelt"]["args"] == ["gdelt", "test-plan"]

    # Reset for other tests
    celery_app.conf.beat_schedule = {}


def test_load_beat_schedule_no_active_plans():
    """When no active plans exist, beat_schedule stays empty and no crash."""
    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("osint_core.db.async_session", mock_session_factory),
        patch(
            "osint_core.services.plan_store.PlanStore.get_all_active",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        load_beat_schedule()

    assert celery_app.conf.beat_schedule == {}


def test_load_beat_schedule_db_error_exits_after_retries():
    """If the database is unreachable after all retries, Beat exits non-zero."""
    with (
        patch(
            "osint_core.workers.celery_app._fetch_active_plans_schedule",
            side_effect=ConnectionError("DB unreachable"),
        ),
        patch("time.sleep"),
        pytest.raises(SystemExit) as exc_info,
    ):
        load_beat_schedule()

    assert exc_info.value.code == 1


def test_load_beat_schedule_multiple_active_plans():
    """Multiple active plans should merge their schedules."""
    plan_a = MagicMock()
    plan_a.plan_id = "plan-a"
    plan_a.version = 1
    plan_a.content = {
        "plan_id": "plan-a",
        "sources": [{"id": "src_a", "type": "rss", "schedule_cron": "0 * * * *"}],
    }
    plan_b = MagicMock()
    plan_b.plan_id = "plan-b"
    plan_b.version = 2
    plan_b.content = {
        "plan_id": "plan-b",
        "sources": [{"id": "src_b", "type": "rss", "schedule_cron": "30 * * * *"}],
    }

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("osint_core.db.async_session", mock_session_factory),
        patch(
            "osint_core.services.plan_store.PlanStore.get_all_active",
            new_callable=AsyncMock,
            return_value=[plan_a, plan_b],
        ),
    ):
        load_beat_schedule()

    schedule = celery_app.conf.beat_schedule
    assert "ingest-plan-a-src_a" in schedule
    assert "ingest-plan-b-src_b" in schedule
    assert schedule["ingest-plan-a-src_a"]["args"] == ["src_a", "plan-a"]
    assert schedule["ingest-plan-b-src_b"]["args"] == ["src_b", "plan-b"]

    # Reset for other tests
    celery_app.conf.beat_schedule = {}
