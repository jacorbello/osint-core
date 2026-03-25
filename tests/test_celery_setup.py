"""Tests for Celery application configuration."""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from celery.beat import PersistentScheduler
from celery.schedules import crontab

from osint_core.workers.celery_app import (
    PlanScheduler,
    celery_app,
    load_beat_schedule,
)


def test_celery_app_configured():
    assert celery_app.main == "osint-core"
    assert "redis" in celery_app.conf.broker_url


def test_celery_queue_routing():
    routes = celery_app.conf.task_routes
    assert "osint.ingest_source" in routes
    assert routes["osint.ingest_source"]["queue"] == "ingest"
    assert routes["osint.score_event"]["queue"] == "score"
    assert routes["osint.send_notification"]["queue"] == "notify"
    assert routes["osint.vectorize_event"]["queue"] == "enrich"
    assert routes["osint.semantic_search"]["queue"] == "enrich"
    assert routes["osint.compile_digest"]["queue"] == "digest"


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


def test_celery_beat_schedule_has_static_tasks_at_import():
    """Beat schedule contains only static tasks at import time; plan tasks added by beat_init."""
    schedule = celery_app.conf.beat_schedule
    # Only the retention purge task should be present before beat_init
    assert "purge-expired-events-daily" in schedule
    assert schedule["purge-expired-events-daily"]["task"] == "osint.purge_expired_events"


def test_load_beat_schedule_with_active_plan():
    """load_beat_schedule populates beat_schedule from active plans, namespaced by plan_id."""
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

    # Reset to static-only schedule for other tests
    celery_app.conf.beat_schedule = {
        k: v for k, v in celery_app.conf.beat_schedule.items()
        if k == "purge-expired-events-daily"
    }


def test_plan_scheduler_is_persistent_scheduler_subclass():
    """PlanScheduler must extend PersistentScheduler to keep shelve persistence."""
    assert issubclass(PlanScheduler, PersistentScheduler)


def test_plan_scheduler_loads_plans_into_beat_schedule_during_setup(tmp_path):
    """PlanScheduler.setup_schedule loads plan tasks so merge_inplace sees them.

    This is the core fix: the default beat_init signal fires AFTER the scheduler
    is created, so dynamically-added entries never reach merge_inplace.
    PlanScheduler calls load_beat_schedule inside setup_schedule — before
    the parent's merge_inplace — so plan entries are present when the shelve
    is populated.
    """
    mock_plan = MagicMock()
    mock_plan.plan_id = "sched-test"
    mock_plan.version = 1
    mock_plan.content = {
        "plan_id": "sched-test",
        "sources": [
            {"id": "src1", "type": "rss", "schedule_cron": "*/30 * * * *"},
        ],
    }

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    # Snapshot and reset beat_schedule to static-only before creating the scheduler
    original_schedule = celery_app.conf.beat_schedule.copy()
    celery_app.conf.beat_schedule = {
        "purge-expired-events-daily": {
            "task": "osint.purge_expired_events",
            "schedule": crontab(hour=3, minute=0),
        },
    }

    with (
        patch("osint_core.db.async_session", mock_session_factory),
        patch(
            "osint_core.services.plan_store.PlanStore.get_all_active",
            new_callable=AsyncMock,
            return_value=[mock_plan],
        ),
    ):
        scheduler = PlanScheduler(
            app=celery_app,
            schedule_filename=str(tmp_path / "celerybeat-schedule"),
        )

    # The scheduler's internal entries must contain the plan task
    assert "ingest-sched-test-src1" in scheduler.schedule
    # And the static purge task must still be present
    assert "purge-expired-events-daily" in scheduler.schedule

    # Restore original schedule
    celery_app.conf.beat_schedule = original_schedule


def test_celery_app_uses_plan_scheduler():
    """The celery app must be configured to use PlanScheduler as its beat scheduler."""
    assert celery_app.conf.beat_scheduler == (
        "osint_core.workers.celery_app:PlanScheduler"
    )


def test_load_beat_schedule_no_active_plans():
    """When no active plans exist, beat_schedule retains only static tasks."""
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

    schedule = celery_app.conf.beat_schedule
    # Static tasks remain, no plan-based tasks added
    assert "purge-expired-events-daily" in schedule
    # No ingest tasks added
    assert not any(k.startswith("ingest-") for k in schedule)


def test_load_beat_schedule_db_error_raises_after_retries():
    """If the database is unreachable, load_beat_schedule raises after exhausting retries."""
    with (
        patch(
            "osint_core.workers.celery_app._fetch_active_plans_schedule",
            side_effect=ConnectionError("DB unreachable"),
        ),
        patch("osint_core.workers.celery_app.time.sleep"),
    ):
        try:
            load_beat_schedule()
        except ConnectionError:
            pass
        else:
            raise AssertionError("Expected ConnectionError to be raised")


def test_load_beat_schedule_db_error_retries_correct_number_of_times():
    """load_beat_schedule retries _BEAT_SCHEDULE_MAX_RETRIES times before giving up."""
    from osint_core.workers.celery_app import _BEAT_SCHEDULE_MAX_RETRIES

    call_count = 0

    def failing_fetch():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("DB unreachable")

    with (
        patch(
            "osint_core.workers.celery_app._fetch_active_plans_schedule",
            side_effect=failing_fetch,
        ),
        patch("osint_core.workers.celery_app.time.sleep"),
        contextlib.suppress(ConnectionError),
    ):
        load_beat_schedule()

    assert call_count == _BEAT_SCHEDULE_MAX_RETRIES


def test_load_beat_schedule_multiple_active_plans():
    """Multiple active plans should merge their schedules, each namespaced by plan_id."""
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

    # Reset to static-only schedule for other tests
    celery_app.conf.beat_schedule = {
        k: v for k, v in celery_app.conf.beat_schedule.items()
        if k == "purge-expired-events-daily"
    }


def test_load_beat_schedule_same_source_id_different_plans_no_collision():
    """Two plans sharing a source id produce distinct namespaced keys without collision."""
    plan_a = MagicMock()
    plan_a.plan_id = "plan-a"
    plan_a.version = 1
    plan_a.content = {
        "plan_id": "plan-a",
        "sources": [{"id": "shared_src", "type": "rss", "schedule_cron": "0 * * * *"}],
    }
    plan_b = MagicMock()
    plan_b.plan_id = "plan-b"
    plan_b.version = 1
    plan_b.content = {
        "plan_id": "plan-b",
        "sources": [{"id": "shared_src", "type": "rss", "schedule_cron": "30 * * * *"}],
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
    assert "ingest-plan-a-shared_src" in schedule
    assert "ingest-plan-b-shared_src" in schedule
    assert schedule["ingest-plan-a-shared_src"]["args"] == ["shared_src", "plan-a"]
    assert schedule["ingest-plan-b-shared_src"]["args"] == ["shared_src", "plan-b"]

    # Reset to static-only schedule for other tests
    celery_app.conf.beat_schedule = {
        k: v for k, v in celery_app.conf.beat_schedule.items()
        if k == "purge-expired-events-daily"
    }
