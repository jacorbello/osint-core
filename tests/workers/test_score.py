"""Tests for the score_event Celery task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from osint_core.workers.score import _severity_gte, rescore_all_events_task, score_event_task

# ---------------------------------------------------------------------------
# _severity_gte helper
# ---------------------------------------------------------------------------


def test_severity_gte_equal():
    assert _severity_gte("high", "high") is True


def test_severity_gte_greater():
    assert _severity_gte("critical", "high") is True


def test_severity_gte_less():
    assert _severity_gte("low", "medium") is False


def test_severity_gte_unknown_returns_false():
    assert _severity_gte("unknown", "low") is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_id: uuid.UUID | None = None,
    source_id: str = "test_source",
    title: str = "Test event",
    summary: str | None = None,
    occurred_at: datetime | None = None,
    indicators: list[Any] | None = None,
    entities: list[Any] | None = None,
    plan_version_id: uuid.UUID | None = None,
    ingested_at: datetime | None = None,
    nlp_summary: str | None = None,
    nlp_relevance: str | None = None,
    corroboration_count: int = 0,
    country_code: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    source_category: str | None = None,
    event_type: str = "generic",
) -> MagicMock:
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.source_id = source_id
    event.title = title
    event.summary = summary
    event.occurred_at = occurred_at or datetime.now(UTC)
    event.ingested_at = ingested_at or datetime.now(UTC)
    event.indicators = indicators or []
    event.entities = entities or []
    event.plan_version_id = plan_version_id
    event.score = None
    event.severity = None
    event.nlp_summary = nlp_summary
    event.nlp_relevance = nlp_relevance
    event.corroboration_count = corroboration_count
    event.country_code = country_code
    event.latitude = latitude
    event.longitude = longitude
    event.source_category = source_category
    event.event_type = event_type
    return event


def _make_db_session(event: Any | None, plan: Any | None = None) -> AsyncMock:
    """Return a mock async session.

    The first execute returns the event; subsequent executes return plan (None by
    default so that plan-version lookups don't inject unexpected MagicMocks).
    """
    db = AsyncMock()

    event_result = MagicMock()
    event_result.scalar_one_or_none.return_value = event

    plan_result = MagicMock()
    plan_result.scalar_one_or_none.return_value = plan

    # First call -> event; all subsequent calls -> plan (usually None)
    db.execute = AsyncMock(side_effect=[event_result, plan_result, plan_result, plan_result])
    db.commit = AsyncMock()
    db.add = MagicMock()

    # Support async context manager
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    return db


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_score_event_task_registered():
    assert score_event_task.name == "osint.score_event"


def test_score_event_task_max_retries():
    assert score_event_task.max_retries == 3


def test_score_event_task_is_bound():
    assert score_event_task.__bound__ is True


def test_rescore_all_events_task_registered():
    assert rescore_all_events_task.name == "osint.rescore_all_events"


# ---------------------------------------------------------------------------
# Missing event
# ---------------------------------------------------------------------------


def test_score_event_missing_event():
    """When the event is not found, task returns not_found status."""
    db = _make_db_session(event=None)

    with patch("osint_core.workers.score.async_session", return_value=db):
        result = score_event_task.apply(args=[str(uuid.uuid4())]).get()

    assert result["score"] is None
    assert result["severity"] is None
    assert result["status"] == "not_found"


# ---------------------------------------------------------------------------
# Low-severity input
# ---------------------------------------------------------------------------


def test_score_event_low_severity():
    """A very old event with no IOCs from an unknown source scores info/low."""
    old_time = datetime(2020, 1, 1, tzinfo=UTC)  # many years ago -> near-zero score
    event = _make_event(occurred_at=old_time, source_id="obscure_feed")

    db = _make_db_session(event=event)

    with patch("osint_core.workers.score.async_session", return_value=db):
        result = score_event_task.apply(args=[str(event.id)]).get()

    assert result["event_id"] == str(event.id)
    assert result["score"] is not None
    assert 0.0 <= result["score"] <= 1.0
    # Very old event decays to near zero — severity is info or low
    assert result["severity"] in ("info", "low")


# ---------------------------------------------------------------------------
# High-severity input
# ---------------------------------------------------------------------------


def test_score_event_high_severity():
    """A fresh event with NLP-marked relevant from a high-reputation source scores high."""
    event = _make_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(UTC),
        indicators=[MagicMock(id=uuid.uuid4()) for _ in range(5)],
        nlp_relevance="relevant",
        corroboration_count=3,
    )

    # Plan with a config that gives cisa_kev high reputation
    plan = MagicMock()
    plan.content = {
        "scoring": {
            "recency_half_life_hours": 48,
            "source_reputation": {"cisa_kev": 1.0},
        }
    }
    event.plan_version_id = uuid.uuid4()

    db = AsyncMock()
    # Calls: event lookup, stored_version lookup, active_version lookup
    event_result = MagicMock()
    event_result.scalar_one_or_none.return_value = event
    stored_version_result = MagicMock()
    stored_version_result.scalar_one_or_none.return_value = plan
    active_version_result = MagicMock()
    active_version_result.scalar_one_or_none.return_value = plan
    db.execute = AsyncMock(side_effect=[event_result, stored_version_result, active_version_result])
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)

    with patch("osint_core.workers.score.async_session", return_value=db):
        result = score_event_task.apply(args=[str(event.id)]).get()

    assert result["score"] is not None
    assert 0.0 <= result["score"] <= 1.0
    assert result["score"] >= 0.5
    assert result["severity"] in ("medium", "high", "critical")


# ---------------------------------------------------------------------------
# Score and severity are written back to the event
# ---------------------------------------------------------------------------


def test_score_event_writes_back_to_event():
    """score and severity should be assigned to the event object."""
    event = _make_event(source_id="nvd_recent", occurred_at=datetime.now(UTC))

    db = _make_db_session(event=event)

    with patch("osint_core.workers.score.async_session", return_value=db):
        result = score_event_task.apply(args=[str(event.id)]).get()

    assert event.score == result["score"]
    assert event.severity == result["severity"]
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# Alert rules trigger send_notification
# ---------------------------------------------------------------------------


def test_score_event_chains_notification_on_alert_rule():
    """When an alert rule matches, send_notification is chained with rule metadata."""
    import asyncio as _asyncio

    from osint_core.workers.score import _score_event_async

    event = _make_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(UTC),
        indicators=[MagicMock(id=uuid.uuid4()) for _ in range(3)],
        nlp_relevance="relevant",
        corroboration_count=2,
    )
    event.plan_version_id = uuid.uuid4()
    event.entities = []

    plan = MagicMock()
    plan.plan_id = uuid.uuid4()
    plan.content = {
        "scoring": {
            "recency_half_life_hours": 48,
            "source_reputation": {"cisa_kev": 1.0},
        },
        "alerts": {
            "rules": [
                {
                    "name": "high-cisa",
                    "condition": {"severity": {"gte": "medium"}},
                    "channels": ["gotify"],
                    "cooldown_minutes": 30,
                }
            ]
        },
    }

    db = AsyncMock()
    event_result = MagicMock()
    event_result.scalar_one_or_none.return_value = event
    stored_version_result = MagicMock()
    stored_version_result.scalar_one_or_none.return_value = plan
    active_version_result = MagicMock()
    active_version_result.scalar_one_or_none.return_value = plan
    alert_result = MagicMock()
    alert_result.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(
        side_effect=[event_result, stored_version_result, active_version_result, alert_result]
    )
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)

    notify_mock = MagicMock()
    notify_mock.delay = MagicMock()

    with (
        patch("osint_core.workers.score.async_session", return_value=db),
        patch("osint_core.workers.notify.send_notification", notify_mock),
    ):
        result = _asyncio.new_event_loop().run_until_complete(
            _score_event_async(str(event.id))
        )

    assert result["severity"] in ("medium", "high", "critical")
    # send_notification.delay should have been called with alert_id and rule list
    notify_mock.delay.assert_called_once()
    call_args = notify_mock.delay.call_args
    assert call_args is not None
    # Second positional arg is the list of rule dicts
    rule_list = call_args[0][1]
    assert isinstance(rule_list, list)
    assert rule_list[0]["name"] == "high-cisa"
