"""Tests for Celery ingest tasks and Beat schedule builder."""

from celery.schedules import crontab

from osint_core.services.plan_engine import PlanEngine
from osint_core.workers.ingest import ingest_source


def test_ingest_source_task_registered():
    """The ingest_source task should be registered with the correct name."""
    assert ingest_source.name == "osint.ingest_source"


def test_ingest_source_task_max_retries():
    """The ingest_source task should have max_retries=3."""
    assert ingest_source.max_retries == 3


def test_ingest_source_is_bound():
    """The ingest_source task should be a bound task (bind=True)."""
    assert ingest_source.__bound__ is True


def test_build_beat_schedule_basic():
    """Build a Beat schedule from a plan with one source using schedule_cron."""
    plan = {
        "sources": [
            {
                "id": "cisa_kev",
                "type": "cisa_kev",
                "url": "https://www.cisa.gov/kev",
                "schedule_cron": "0 */6 * * *",
            }
        ]
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    assert "ingest-cisa_kev" in schedule
    entry = schedule["ingest-cisa_kev"]
    assert entry["task"] == "osint.ingest_source"
    assert entry["args"] == ["cisa_kev"]
    assert isinstance(entry["schedule"], crontab)


def test_build_beat_schedule_multiple_sources():
    """Build a Beat schedule from a plan with multiple sources."""
    plan = {
        "sources": [
            {
                "id": "cisa_kev",
                "type": "cisa_kev",
                "schedule_cron": "0 */6 * * *",
            },
            {
                "id": "nvd_feed",
                "type": "nvd_json_feed",
                "schedule_cron": "30 * * * *",
            },
            {
                "id": "threatfox",
                "type": "threatfox_api",
                "schedule_cron": "*/15 * * * *",
            },
        ]
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    assert len(schedule) == 3
    assert "ingest-cisa_kev" in schedule
    assert "ingest-nvd_feed" in schedule
    assert "ingest-threatfox" in schedule


def test_build_beat_schedule_skips_sources_without_cron():
    """Sources without schedule_cron should be skipped in the Beat schedule."""
    plan = {
        "sources": [
            {
                "id": "manual_source",
                "type": "rss",
                "url": "https://example.com/feed.xml",
            },
            {
                "id": "scheduled_source",
                "type": "cisa_kev",
                "schedule_cron": "0 12 * * *",
            },
        ]
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    assert len(schedule) == 1
    assert "ingest-scheduled_source" in schedule
    assert "ingest-manual_source" not in schedule


def test_build_beat_schedule_empty_sources():
    """An empty sources list should produce an empty schedule."""
    plan = {"sources": []}
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    assert schedule == {}


def test_build_beat_schedule_cron_parsing():
    """Verify cron expression is correctly parsed into minute/hour/day_of_week etc."""
    plan = {
        "sources": [
            {
                "id": "test_src",
                "type": "rss",
                "schedule_cron": "30 6 * * 1-5",
            }
        ]
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    entry = schedule["ingest-test_src"]
    cron = entry["schedule"]
    assert isinstance(cron, crontab)


def test_build_beat_schedule_options_queue():
    """Beat schedule entries should route to the 'ingest' queue."""
    plan = {
        "sources": [
            {
                "id": "src1",
                "type": "cisa_kev",
                "schedule_cron": "0 * * * *",
            }
        ]
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    entry = schedule["ingest-src1"]
    assert entry["options"]["queue"] == "ingest"
