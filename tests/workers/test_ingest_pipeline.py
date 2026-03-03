"""Tests for the full ingest pipeline (_ingest_source_async)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.connectors.base import RawItem
from osint_core.workers.ingest import _ingest_source_async


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(plan_id: str = "plan-1", sources: list | None = None):
    """Create a mock PlanVersion object."""
    plan = SimpleNamespace(
        id=uuid.uuid4(),
        plan_id=plan_id,
        content={
            "sources": sources or [
                {
                    "id": "src-1",
                    "type": "rss",
                    "url": "https://example.com/feed.xml",
                    "weight": 1.0,
                    "params": {},
                }
            ],
        },
    )
    return plan


def _make_raw_item(title: str = "Test Item", url: str = "https://example.com/1"):
    """Create a RawItem for testing."""
    return RawItem(
        title=title,
        url=url,
        raw_data={"key": title},
        summary=f"Summary of {title}",
        occurred_at=datetime(2025, 1, 1, tzinfo=UTC),
        severity="low",
    )


def _mock_task_self():
    """Create a mock Celery task self object."""
    task_self = MagicMock()
    task_self.request.id = "celery-task-id-123"
    task_self.request.retries = 0
    return task_self


def _make_mock_db():
    """Create a mock async DB session with proper async methods."""
    mock_db = AsyncMock()
    # Default: no duplicate found (scalar_one_or_none returns None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    # The event needs an id after flush
    mock_db.add = MagicMock()
    return mock_db


def _patch_all(mock_db, mock_plan, mock_items, extract_return=None):
    """Return a dict of patch targets and their mocks."""
    # async_session context manager — need to handle multiple calls
    # (main pipeline + _record_job)
    mock_session_factory = MagicMock()
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory.return_value = mock_session_ctx

    # For _record_job, we need a second session
    mock_job_db = AsyncMock()
    mock_job_db.add = MagicMock()
    mock_job_db.commit = AsyncMock()
    mock_job_ctx = AsyncMock()
    mock_job_ctx.__aenter__ = AsyncMock(return_value=mock_job_db)
    mock_job_ctx.__aexit__ = AsyncMock(return_value=False)

    # Make the factory return main db first, then job db
    mock_session_factory.side_effect = [mock_session_ctx, mock_job_ctx]

    # plan_store
    mock_plan_store = MagicMock()
    mock_plan_store.get_active = AsyncMock(return_value=mock_plan)

    # registry / connector
    mock_connector = AsyncMock()
    mock_connector.fetch = AsyncMock(return_value=mock_items)
    mock_registry = MagicMock()
    mock_registry.get = MagicMock(return_value=mock_connector)

    # downstream tasks
    mock_score = MagicMock()
    mock_vectorize = MagicMock()
    mock_correlate = MagicMock()

    # extract_indicators
    if extract_return is None:
        extract_return = []

    patches = {
        "async_session": mock_session_factory,
        "plan_store": mock_plan_store,
        "registry": mock_registry,
        "score_event_task": mock_score,
        "vectorize_event_task": mock_vectorize,
        "correlate_event_task": mock_correlate,
        "extract_indicators": extract_return,
    }
    return patches


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_creates_events():
    """Two RawItems fetched => both persisted, downstream tasks chained, ingested=2."""
    plan = _make_plan()
    items = [_make_raw_item("Item 1", "https://a.com/1"), _make_raw_item("Item 2", "https://a.com/2")]
    mock_db = _make_mock_db()
    patches = _patch_all(mock_db, plan, items, extract_return=[{"type": "cve", "value": "CVE-2025-0001"}])
    task_self = _mock_task_self()

    # We need events to get UUIDs after flush — patch Event so .id is set
    event_ids = [uuid.uuid4(), uuid.uuid4()]
    event_id_iter = iter(event_ids)

    original_add = mock_db.add

    def side_effect_add(obj):
        """Assign a UUID id to Event objects when added."""
        if hasattr(obj, "event_type"):
            obj.id = next(event_id_iter)
        return original_add(obj)

    mock_db.add = MagicMock(side_effect=side_effect_add)

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
        patch("osint_core.workers.ingest.score_event_task", patches["score_event_task"]),
        patch("osint_core.workers.ingest.vectorize_event_task", patches["vectorize_event_task"]),
        patch("osint_core.workers.ingest.correlate_event_task", patches["correlate_event_task"]),
        patch("osint_core.workers.ingest.extract_indicators", return_value=[{"type": "cve", "value": "CVE-2025-0001"}]),
    ):
        result = await _ingest_source_async(task_self, "src-1", "plan-1")

    assert result["ingested"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert result["status"] == "succeeded"

    # Downstream tasks should be called for each event
    assert patches["score_event_task"].delay.call_count == 2
    assert patches["vectorize_event_task"].delay.call_count == 2
    assert patches["correlate_event_task"].delay.call_count == 2


@pytest.mark.asyncio
async def test_ingest_skips_duplicates():
    """When dedupe query returns an existing ID, item is skipped."""
    plan = _make_plan()
    items = [_make_raw_item("Dup Item")]
    mock_db = _make_mock_db()

    # Make the dedupe check return an existing event ID (= duplicate)
    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = uuid.uuid4()  # existing event
    mock_db.execute = AsyncMock(return_value=dup_result)

    patches = _patch_all(mock_db, plan, items)
    task_self = _mock_task_self()

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
        patch("osint_core.workers.ingest.score_event_task", patches["score_event_task"]),
        patch("osint_core.workers.ingest.vectorize_event_task", patches["vectorize_event_task"]),
        patch("osint_core.workers.ingest.correlate_event_task", patches["correlate_event_task"]),
        patch("osint_core.workers.ingest.extract_indicators", return_value=[]),
    ):
        result = await _ingest_source_async(task_self, "src-1", "plan-1")

    assert result["skipped"] == 1
    assert result["ingested"] == 0
    assert result["errors"] == 0

    # No downstream tasks should be called
    assert patches["score_event_task"].delay.call_count == 0


@pytest.mark.asyncio
async def test_ingest_raises_for_missing_plan():
    """When plan_store returns None, ValueError is raised."""
    mock_db = _make_mock_db()
    patches = _patch_all(mock_db, None, [])  # plan=None
    task_self = _mock_task_self()

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
    ):
        with pytest.raises(ValueError, match="No active plan"):
            await _ingest_source_async(task_self, "src-1", "plan-1")


@pytest.mark.asyncio
async def test_ingest_raises_for_missing_source():
    """When source_id is not in plan.content.sources, ValueError is raised."""
    plan = _make_plan(sources=[
        {"id": "other-source", "type": "rss", "url": "https://example.com", "weight": 1.0}
    ])
    mock_db = _make_mock_db()
    patches = _patch_all(mock_db, plan, [])
    task_self = _mock_task_self()

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
    ):
        with pytest.raises(ValueError, match="Source .* not in plan"):
            await _ingest_source_async(task_self, "src-1", "plan-1")


@pytest.mark.asyncio
async def test_ingest_error_rate_threshold():
    """When >50% of items fail processing, RuntimeError is raised."""
    plan = _make_plan()
    # 4 items, 3 will fail
    items = [_make_raw_item(f"Item {i}") for i in range(4)]
    mock_db = _make_mock_db()
    task_self = _mock_task_self()

    call_count = 0

    # Make the dedupe check pass (no dup), but flush raises for 3 of 4 items
    original_execute = mock_db.execute

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)

    flush_call_count = {"n": 0}

    async def flush_side_effect():
        flush_call_count["n"] += 1
        if flush_call_count["n"] % 4 != 1:
            # Fail 3 out of 4
            raise Exception("Simulated processing error")

    mock_db.flush = AsyncMock(side_effect=flush_side_effect)

    patches = _patch_all(mock_db, plan, items)
    # Override the session factory since _patch_all already set it up,
    # but we need it to return our custom mock_db
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    patches["async_session"].side_effect = [mock_session_ctx]

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
        patch("osint_core.workers.ingest.score_event_task", patches["score_event_task"]),
        patch("osint_core.workers.ingest.vectorize_event_task", patches["vectorize_event_task"]),
        patch("osint_core.workers.ingest.correlate_event_task", patches["correlate_event_task"]),
        patch("osint_core.workers.ingest.extract_indicators", return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="High error rate"):
            await _ingest_source_async(task_self, "src-1", "plan-1")
