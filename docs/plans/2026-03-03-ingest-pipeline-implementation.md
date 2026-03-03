# Ingest Pipeline Wiring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the stub `ingest_source` Celery task with a working implementation that fetches from connectors, deduplicates, persists events and indicators, chains downstream tasks, and records Jobs.

**Architecture:** Minimal wiring (Approach A) — all logic in a single async function inside `workers/ingest.py`, called via `asyncio.run()` from the sync Celery task. Required `plan_id` argument end-to-end. Concurrency-safe upserts via pre-check + IntegrityError handling.

**Tech Stack:** Python 3.12, Celery 5.x, SQLAlchemy 2.x async, PostgreSQL (osint schema), Alembic, pytest + pytest-asyncio

**Design doc:** `docs/plans/2026-03-03-ingest-pipeline-wiring-design.md`

---

### Task 1: Alembic Migration — Add `partial_success` to Job Status CHECK

**Files:**
- Create: `migrations/versions/0004_add_partial_success_job_status.py`
- Reference: `migrations/versions/0001_initial_schema.py` (line 489-492 for existing CHECK)

**Context:** The Job model's `status_check` constraint currently allows: `queued`, `running`, `succeeded`, `failed`, `dead_letter`. We need to add `partial_success` for when some items ingest successfully but others error.

**Important:** Run `alembic heads` first to determine the current head revision. The migration must chain after whatever the latest revision is (may be `0001`, `0002`, or `0003` depending on branch state). Adjust `down_revision` accordingly.

**Step 1: Check current Alembic head**

Run: `cd /root/repos/personal/osint-core && python -m alembic heads`

Note the current head revision ID — use it as `down_revision` in the migration.

**Step 2: Create the migration file**

```python
"""add partial_success to job status check

Revision ID: 0004
Revises: <CURRENT_HEAD>
Create Date: 2026-03-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "<CURRENT_HEAD>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_jobs_status_check", "jobs", schema="osint")
    op.create_check_constraint(
        "ck_jobs_status_check",
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')",
        schema="osint",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_status_check", "jobs", schema="osint")
    op.create_check_constraint(
        "ck_jobs_status_check",
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')",
        schema="osint",
    )
```

**Step 3: Update the Job model CHECK to match**

In `src/osint_core/models/job.py:52-55`, update the CheckConstraint string:

```python
CheckConstraint(
    "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')",
    name="status_check",
),
```

**Step 4: Run tests to verify nothing broke**

Run: `pytest tests/ -v -x --ignore=tests/integration -q`

Expected: All existing tests pass (migration doesn't affect unit tests).

**Step 5: Commit**

```bash
git add migrations/versions/0004_add_partial_success_job_status.py src/osint_core/models/job.py
git commit -m "feat(db): add partial_success to Job status CHECK constraint"
```

---

### Task 2: Update Beat Schedule Builder to Pass `plan_id`

**Files:**
- Modify: `src/osint_core/services/plan_engine.py:92-103` (build_beat_schedule method)
- Modify: `tests/workers/test_ingest.py` (Beat schedule tests, lines 24-138)

**Context:** `build_beat_schedule()` currently puts `[source_id]` in `args`. It needs to also pass `plan_id` since the task signature now requires it. The method needs the `plan_id` as a parameter.

**Step 1: Write the failing test**

Add to `tests/workers/test_ingest.py`:

```python
def test_build_beat_schedule_includes_plan_id():
    """Beat schedule entries should include plan_id in task args."""
    plan = {
        "plan_id": "military-intel",
        "sources": [
            {
                "id": "cisa_kev",
                "type": "cisa_kev",
                "url": "https://www.cisa.gov/kev",
                "schedule_cron": "0 */6 * * *",
            }
        ],
    }
    engine = PlanEngine()
    schedule = engine.build_beat_schedule(plan)
    entry = schedule["ingest-cisa_kev"]
    assert entry["args"] == ["cisa_kev", "military-intel"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/workers/test_ingest.py::test_build_beat_schedule_includes_plan_id -v`

Expected: FAIL — `["cisa_kev"] != ["cisa_kev", "military-intel"]`

**Step 3: Update build_beat_schedule to pass plan_id**

In `src/osint_core/services/plan_engine.py`, update the `build_beat_schedule` method (lines 80-104):

```python
def build_beat_schedule(self, plan: dict[str, Any]) -> dict[str, Any]:
    """Convert a plan's sources list into a Celery Beat schedule.

    Only sources with a ``schedule_cron`` field are included.  Each entry
    dispatches the ``osint.ingest_source`` task to the ``ingest`` queue.

    Args:
        plan: Parsed plan dict (must contain ``plan_id`` and ``sources`` keys).

    Returns:
        Dict suitable for ``celery_app.conf.beat_schedule``.
    """
    plan_id = plan.get("plan_id", "")
    schedule: dict[str, Any] = {}
    for source in plan.get("sources", []):
        cron_expr = source.get("schedule_cron")
        if not cron_expr:
            continue
        source_id = source["id"]
        schedule[f"ingest-{source_id}"] = {
            "task": "osint.ingest_source",
            "schedule": _parse_cron(cron_expr),
            "args": [source_id, plan_id],
            "options": {"queue": "ingest"},
        }
    return schedule
```

**Step 4: Fix existing Beat schedule tests**

The existing tests that assert `entry["args"] == ["cisa_kev"]` will now fail because args includes `plan_id`. Update each test's plan dict to include `"plan_id"` and update assertions:

- `test_build_beat_schedule_basic`: Add `"plan_id": "test-plan"` to plan dict, assert `entry["args"] == ["cisa_kev", "test-plan"]`
- `test_build_beat_schedule_multiple_sources`: Add `"plan_id": "test-plan"` to plan dict
- `test_build_beat_schedule_skips_sources_without_cron`: Add `"plan_id": "test-plan"`
- `test_build_beat_schedule_empty_sources`: No change needed (no entries to check args on)
- `test_build_beat_schedule_cron_parsing`: Add `"plan_id": "test-plan"`
- `test_build_beat_schedule_options_queue`: Add `"plan_id": "test-plan"`

For tests that don't provide `plan_id`, the schedule will use `""` (empty string) from `plan.get("plan_id", "")` — this is fine for backward compat, but update them to be explicit.

**Step 5: Run all Beat schedule tests**

Run: `pytest tests/workers/test_ingest.py -v`

Expected: All pass.

**Step 6: Commit**

```bash
git add src/osint_core/services/plan_engine.py tests/workers/test_ingest.py
git commit -m "feat: pass plan_id in Beat schedule task args"
```

---

### Task 3: Update API Route to Accept and Pass `plan_id`

**Files:**
- Modify: `src/osint_core/api/routes/ingest.py` (all 31 lines)
- Create: `tests/api/test_ingest_route.py`

**Context:** The API route at `POST /api/v1/ingest/source/{source_id}/run` currently calls `ingest_source.delay(source_id)`. It needs to accept `plan_id` as a required body/query parameter and pass it through.

**Step 1: Write the failing test**

Create `tests/api/test_ingest_route.py`:

```python
"""Tests for the ingest API route — plan_id is required."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with auth dependency overridden."""
    from osint_core.api.app import app
    from osint_core.api.deps import get_current_user
    from osint_core.api.middleware.auth import UserInfo

    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        sub="test-user", roles=["admin"]
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@patch("osint_core.api.routes.ingest.ingest_source")
def test_run_ingest_requires_plan_id(mock_task, client):
    """POST /api/v1/ingest/source/{source_id}/run requires plan_id query param."""
    mock_task.delay.return_value = MagicMock(id="task-123")
    response = client.post(
        "/api/v1/ingest/source/bbc_world/run?plan_id=military-intel"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["plan_id"] == "military-intel"
    assert data["source_id"] == "bbc_world"
    mock_task.delay.assert_called_once_with("bbc_world", "military-intel")


@patch("osint_core.api.routes.ingest.ingest_source")
def test_run_ingest_missing_plan_id_returns_422(mock_task, client):
    """POST without plan_id should return 422."""
    response = client.post("/api/v1/ingest/source/bbc_world/run")
    assert response.status_code == 422
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_ingest_route.py -v`

Expected: FAIL — current route doesn't accept `plan_id`, doesn't include it in response.

Note: If the test client fixture fails due to app import issues (missing env vars, etc.), check `tests/conftest.py` for the `settings` fixture and ensure env vars are set or the app handles missing config gracefully. You may need to set `DATABASE_URL` and other env vars for the app to import. If so, use monkeypatch or set them in the fixture.

**Step 3: Update the API route**

Replace `src/osint_core/api/routes/ingest.py`:

```python
"""Ingest API routes — dispatch Celery ingest tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from osint_core.api.deps import get_current_user
from osint_core.api.middleware.auth import UserInfo
from osint_core.workers.ingest import ingest_source

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


@router.post("/source/{source_id}/run")
async def run_ingest(
    source_id: str,
    plan_id: str = Query(..., description="Plan ID to ingest against"),
    current_user: UserInfo = Depends(get_current_user),
) -> dict[str, Any]:
    """Dispatch a Celery task to ingest from the specified source.

    Returns the Celery task ID for tracking.
    """
    task = ingest_source.delay(source_id, plan_id)
    return {
        "task_id": task.id,
        "source_id": source_id,
        "plan_id": plan_id,
        "status": "dispatched",
    }
```

**Step 4: Run tests**

Run: `pytest tests/api/test_ingest_route.py -v`

Expected: Both tests pass.

**Step 5: Commit**

```bash
git add src/osint_core/api/routes/ingest.py tests/api/test_ingest_route.py
git commit -m "feat(api): require plan_id in ingest dispatch endpoint"
```

---

### Task 4: Implement `_ingest_source_async` Core Logic

**Files:**
- Modify: `src/osint_core/workers/ingest.py` (replace lines 21-66)
- Reference: `src/osint_core/connectors/__init__.py` (registry at line 26)
- Reference: `src/osint_core/connectors/base.py` (SourceConfig, RawItem)
- Reference: `src/osint_core/models/event.py` (Event model)
- Reference: `src/osint_core/models/indicator.py` (Indicator model)
- Reference: `src/osint_core/models/job.py` (Job model)
- Reference: `src/osint_core/services/plan_store.py` (PlanStore)
- Reference: `src/osint_core/services/indicators.py` (extract_indicators)
- Reference: `src/osint_core/db.py` (async_session)
- Reference: `src/osint_core/workers/score.py` (score_event_task)
- Reference: `src/osint_core/workers/enrich.py` (vectorize_event_task, correlate_event_task)

**Context:** This is the main implementation task. Replace the stub with the full async pipeline.

**Step 1: Write the failing tests**

Create `tests/workers/test_ingest_pipeline.py`:

```python
"""Tests for the ingest_source task — full pipeline logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.workers.ingest import _dedupe_fingerprint, _ingest_source_async


def _make_raw_item(**overrides) -> RawItem:
    """Create a RawItem with sensible defaults."""
    defaults = {
        "title": "Test Vulnerability CVE-2026-1234",
        "url": "https://example.com/vuln/1",
        "raw_data": {"id": "vuln-1", "description": "A test vulnerability"},
        "summary": "Critical vulnerability in 192.168.1.1",
        "occurred_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "severity": "high",
        "indicators": [],
    }
    defaults.update(overrides)
    return RawItem(**defaults)


def _make_plan_version(plan_id="test-plan", sources=None):
    """Create a mock PlanVersion."""
    pv = MagicMock()
    pv.id = uuid.uuid4()
    pv.plan_id = plan_id
    pv.content = {
        "plan_id": plan_id,
        "sources": sources or [
            {
                "id": "test_source",
                "type": "rss",
                "url": "https://example.com/feed.xml",
                "weight": 1.0,
            }
        ],
    }
    return pv


@pytest.mark.asyncio
@patch("osint_core.workers.ingest.async_session")
@patch("osint_core.workers.ingest.plan_store")
@patch("osint_core.workers.ingest.registry")
@patch("osint_core.workers.ingest.score_event_task")
@patch("osint_core.workers.ingest.vectorize_event_task")
@patch("osint_core.workers.ingest.correlate_event_task")
async def test_ingest_creates_events(
    mock_correlate, mock_vectorize, mock_score,
    mock_registry, mock_plan_store, mock_session_factory,
):
    """Ingest should create Event records for each fetched RawItem."""
    plan = _make_plan_version()
    mock_plan_store.get_active = AsyncMock(return_value=plan)

    items = [_make_raw_item(), _make_raw_item(title="Second Item", raw_data={"id": "vuln-2"})]
    connector = AsyncMock()
    connector.fetch = AsyncMock(return_value=items)
    mock_registry.get.return_value = connector

    # Mock DB session
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_self = MagicMock()
    mock_self.request.id = "celery-task-123"

    result = await _ingest_source_async(mock_self, "test_source", "test-plan")

    assert result["ingested"] == 2
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert result["status"] == "succeeded"
    assert mock_db.add.call_count >= 2  # At least 2 events
    mock_score.delay.assert_called()
    mock_vectorize.delay.assert_called()
    mock_correlate.delay.assert_called()


@pytest.mark.asyncio
@patch("osint_core.workers.ingest.async_session")
@patch("osint_core.workers.ingest.plan_store")
@patch("osint_core.workers.ingest.registry")
async def test_ingest_skips_duplicates(
    mock_registry, mock_plan_store, mock_session_factory,
):
    """Items with existing dedupe_fingerprint should be skipped."""
    plan = _make_plan_version()
    mock_plan_store.get_active = AsyncMock(return_value=plan)

    items = [_make_raw_item()]
    connector = AsyncMock()
    connector.fetch = AsyncMock(return_value=items)
    mock_registry.get.return_value = connector

    # Mock DB — dedupe query returns existing ID (= duplicate)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = uuid.uuid4()
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=existing_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_self = MagicMock()
    mock_self.request.id = "celery-task-456"

    result = await _ingest_source_async(mock_self, "test_source", "test-plan")

    assert result["ingested"] == 0
    assert result["skipped"] == 1


@pytest.mark.asyncio
@patch("osint_core.workers.ingest.async_session")
@patch("osint_core.workers.ingest.plan_store")
async def test_ingest_raises_for_missing_plan(mock_plan_store, mock_session_factory):
    """Should raise ValueError if no active plan found."""
    mock_plan_store.get_active = AsyncMock(return_value=None)

    mock_db = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_self = MagicMock()
    with pytest.raises(ValueError, match="No active plan"):
        await _ingest_source_async(mock_self, "test_source", "nonexistent-plan")


@pytest.mark.asyncio
@patch("osint_core.workers.ingest.async_session")
@patch("osint_core.workers.ingest.plan_store")
async def test_ingest_raises_for_missing_source(mock_plan_store, mock_session_factory):
    """Should raise ValueError if source_id not in plan."""
    plan = _make_plan_version(sources=[{"id": "other_source", "type": "rss", "url": "https://example.com"}])
    mock_plan_store.get_active = AsyncMock(return_value=plan)

    mock_db = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_self = MagicMock()
    with pytest.raises(ValueError, match="not in plan"):
        await _ingest_source_async(mock_self, "missing_source", "test-plan")


@pytest.mark.asyncio
@patch("osint_core.workers.ingest.async_session")
@patch("osint_core.workers.ingest.plan_store")
@patch("osint_core.workers.ingest.registry")
async def test_ingest_error_rate_threshold(
    mock_registry, mock_plan_store, mock_session_factory,
):
    """Should raise RuntimeError when >50% of items fail processing."""
    plan = _make_plan_version()
    mock_plan_store.get_active = AsyncMock(return_value=plan)

    items = [_make_raw_item(raw_data={"id": f"item-{i}"}) for i in range(4)]
    connector = AsyncMock()
    connector.fetch = AsyncMock(return_value=items)
    mock_registry.get.return_value = connector

    # Mock DB — first call returns no dup, but flush raises for 3 out of 4 items
    call_count = {"n": 0}
    def mock_execute_side_effect(*args, **kwargs):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=mock_execute_side_effect)

    flush_count = {"n": 0}
    async def mock_flush():
        flush_count["n"] += 1
        if flush_count["n"] % 4 != 0:  # 3 out of 4 fail
            raise Exception("Simulated DB error")
    mock_db.flush = mock_flush
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_self = MagicMock()
    mock_self.request.id = "celery-task-789"

    with pytest.raises(RuntimeError, match="High error rate"):
        await _ingest_source_async(mock_self, "test_source", "test-plan")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/workers/test_ingest_pipeline.py -v`

Expected: FAIL — `_ingest_source_async` not defined (only stub exists).

**Step 3: Implement the full `workers/ingest.py`**

Replace the entire file `src/osint_core/workers/ingest.py`:

```python
"""Celery ingest tasks — fetch items from configured sources and create events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osint_core.connectors import registry
from osint_core.connectors.base import SourceConfig
from osint_core.db import async_session
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from osint_core.services.indicators import extract_indicators
from osint_core.services.plan_store import PlanStore
from osint_core.workers.celery_app import celery_app
from osint_core.workers.enrich import correlate_event_task, vectorize_event_task
from osint_core.workers.score import score_event_task

logger = logging.getLogger(__name__)

plan_store = PlanStore()

ERROR_RATE_THRESHOLD = 0.5


def _dedupe_fingerprint(source_id: str, item_data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint for deduplication."""
    payload = json.dumps({"source": source_id, **item_data}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@celery_app.task(bind=True, name="osint.ingest_source", max_retries=3)
def ingest_source(self: Any, source_id: str, plan_id: str) -> dict[str, Any]:
    """Ingest items from a configured source.

    Wraps the async implementation with asyncio.run().
    Config errors (ValueError, KeyError) are not retried.
    Transient errors are retried with capped exponential backoff.
    """
    try:
        return asyncio.run(_ingest_source_async(self, source_id, plan_id))
    except (ValueError, KeyError) as exc:
        logger.error("Ingest config error for %s: %s", source_id, exc)
        asyncio.run(_record_failed_job(self, plan_id, source_id, str(exc)))
        return {
            "source_id": source_id,
            "plan_id": plan_id,
            "status": "failed",
            "error": str(exc),
            "ingested": 0,
            "skipped": 0,
            "errors": 0,
        }
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)
        raise self.retry(exc=exc, countdown=countdown)


async def _ingest_source_async(
    task_self: Any,
    source_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Async implementation of the ingest pipeline."""
    ingested = 0
    skipped = 0
    errors = 0
    new_event_ids: list[str] = []
    plan_version_id = None

    async with async_session() as db:
        # Step 1: Resolve plan & source config
        plan = await plan_store.get_active(db, plan_id)
        if not plan:
            raise ValueError(f"No active plan for plan_id={plan_id}")

        plan_version_id = plan.id
        source_cfg_dict = next(
            (s for s in plan.content.get("sources", []) if s["id"] == source_id),
            None,
        )
        if not source_cfg_dict:
            raise ValueError(f"Source {source_id} not in plan {plan_id}")

        source_cfg = SourceConfig(
            id=source_cfg_dict["id"],
            type=source_cfg_dict["type"],
            url=source_cfg_dict.get("url", ""),
            weight=source_cfg_dict.get("weight", 1.0),
            extra=source_cfg_dict.get("params", {}),
        )

        # Step 2: Fetch items
        connector = registry.get(source_cfg.type, source_cfg)
        items = await connector.fetch()
        logger.info("Fetched %d items from %s", len(items), source_id)

        # Step 3: Dedupe & persist each item
        for item in items:
            try:
                fingerprint = _dedupe_fingerprint(source_id, item.raw_data)

                # Pre-check for duplicate (fast path)
                result = await db.execute(
                    select(Event.id).where(Event.dedupe_fingerprint == fingerprint)
                )
                if result.scalar_one_or_none() is not None:
                    skipped += 1
                    continue

                # Create Event
                event = Event(
                    event_type=source_cfg.type,
                    source_id=source_id,
                    title=item.title,
                    summary=item.summary,
                    raw_excerpt=item.url,
                    occurred_at=item.occurred_at,
                    severity=item.severity,
                    dedupe_fingerprint=fingerprint,
                    metadata_=item.raw_data,
                    plan_version_id=plan.id,
                )
                db.add(event)

                try:
                    await db.flush()
                except IntegrityError:
                    await db.rollback()
                    skipped += 1
                    continue

                # Extract and link indicators
                indicator_dicts = extract_indicators(
                    f"{item.title} {item.summary}"
                )
                for ind_dict in indicator_dicts:
                    indicator = await _upsert_indicator(
                        db, ind_dict, source_id
                    )
                    if indicator is not None:
                        event.indicators.append(indicator)

                new_event_ids.append(str(event.id))
                ingested += 1

            except Exception:
                logger.exception("Failed to process item from %s", source_id)
                await db.rollback()
                errors += 1

        # Step 4: Error rate check
        if items and len(items) > 0 and errors / len(items) > ERROR_RATE_THRESHOLD:
            raise RuntimeError(
                f"High error rate: {errors}/{len(items)} items failed for {source_id}"
            )

        # Step 5: Commit
        await db.commit()

    # Step 6: Chain downstream tasks
    for event_id in new_event_ids:
        score_event_task.delay(event_id)
        vectorize_event_task.delay(event_id)
        correlate_event_task.delay(event_id)

    # Step 7: Record Job
    if errors > 0 and ingested > 0:
        job_status = "partial_success"
    elif errors > 0:
        job_status = "failed"
    else:
        job_status = "succeeded"

    await _record_job(
        task_self, plan_version_id, source_id, plan_id,
        job_status, ingested, skipped, errors,
    )

    return {
        "source_id": source_id,
        "plan_id": plan_id,
        "status": job_status,
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }


async def _upsert_indicator(
    db: Any,
    ind_dict: dict[str, Any],
    source_id: str,
) -> Indicator | None:
    """Insert or fetch an existing indicator, merging source_id into sources."""
    # Try to find existing
    result = await db.execute(
        select(Indicator).where(
            Indicator.indicator_type == ind_dict["type"],
            Indicator.value == ind_dict["value"],
        )
    )
    indicator = result.scalar_one_or_none()

    if indicator is not None:
        # Merge source_id if missing
        if source_id not in (indicator.sources or []):
            indicator.sources = [*(indicator.sources or []), source_id]
        return indicator

    # Try insert
    indicator = Indicator(
        indicator_type=ind_dict["type"],
        value=ind_dict["value"],
        sources=[source_id],
    )
    db.add(indicator)
    try:
        await db.flush()
        return indicator
    except IntegrityError:
        await db.rollback()
        # Re-fetch after race condition
        result = await db.execute(
            select(Indicator).where(
                Indicator.indicator_type == ind_dict["type"],
                Indicator.value == ind_dict["value"],
            )
        )
        indicator = result.scalar_one_or_none()
        if indicator and source_id not in (indicator.sources or []):
            indicator.sources = [*(indicator.sources or []), source_id]
        return indicator


async def _record_job(
    task_self: Any,
    plan_version_id: Any,
    source_id: str,
    plan_id: str,
    status: str,
    ingested: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> None:
    """Record a Job entry for this ingest run."""
    async with async_session() as db:
        job = Job(
            job_type="ingest",
            status=status,
            celery_task_id=getattr(task_self.request, "id", None),
            plan_version_id=plan_version_id,
            input_params={"source_id": source_id, "plan_id": plan_id},
            output={"ingested": ingested, "skipped": skipped, "errors": errors},
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()


async def _record_failed_job(
    task_self: Any,
    plan_id: str,
    source_id: str,
    error_msg: str,
) -> None:
    """Record a failed Job entry (for config errors that don't retry)."""
    async with async_session() as db:
        job = Job(
            job_type="ingest",
            status="failed",
            celery_task_id=getattr(task_self.request, "id", None),
            input_params={"source_id": source_id, "plan_id": plan_id},
            error=error_msg,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
```

**Step 4: Run the pipeline tests**

Run: `pytest tests/workers/test_ingest_pipeline.py -v`

Expected: All 5 tests pass.

**Step 5: Run all existing tests to check for regressions**

Run: `pytest tests/ -v -x --ignore=tests/integration -q`

Expected: All pass. The existing `test_ingest.py` tests for task registration should still pass since the task name, max_retries, and bind status haven't changed.

Note: The existing test `test_ingest_source_task_registered` imports `ingest_source` — it should still work since the function signature changed but the Celery registration metadata is the same.

**Step 6: Commit**

```bash
git add src/osint_core/workers/ingest.py tests/workers/test_ingest_pipeline.py
git commit -m "feat: implement ingest_source pipeline — fetch, dedupe, persist, chain"
```

---

### Task 5: Verify End-to-End and Clean Up

**Files:**
- Review: All files modified in Tasks 1-4
- Run: Full test suite

**Step 1: Run the full non-integration test suite**

Run: `pytest tests/ -v --ignore=tests/integration --tb=short`

Expected: All tests pass with no failures.

**Step 2: Run type checking**

Run: `mypy src/osint_core/workers/ingest.py --ignore-missing-imports`

Expected: No errors (or only pre-existing ones). Fix any type errors introduced.

**Step 3: Run linting**

Run: `ruff check src/osint_core/workers/ingest.py src/osint_core/services/plan_engine.py src/osint_core/api/routes/ingest.py`

Expected: No new violations. Fix any that appear.

**Step 4: Review the diff**

Run: `git diff main --stat` and `git log --oneline main..HEAD`

Verify the changeset matches expectations:
- `migrations/versions/0004_add_partial_success_job_status.py` (new)
- `src/osint_core/models/job.py` (CHECK constraint update)
- `src/osint_core/services/plan_engine.py` (plan_id in beat schedule)
- `src/osint_core/api/routes/ingest.py` (required plan_id param)
- `src/osint_core/workers/ingest.py` (full implementation)
- `tests/workers/test_ingest.py` (updated beat schedule tests)
- `tests/workers/test_ingest_pipeline.py` (new pipeline tests)
- `tests/api/test_ingest_route.py` (new route tests)

**Step 5: Final commit (if any fixes needed)**

```bash
git add -u
git commit -m "fix: address lint/type issues in ingest pipeline"
```
