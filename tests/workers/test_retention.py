"""Tests for the Celery retention cleanup worker task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.retention import (
    RETENTION_THRESHOLDS,
    _create_audit_log,
    _purge_events_by_retention_class,
    _purge_expired_events_async,
    _remove_qdrant_vectors,
    purge_expired_events,
)

# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def test_purge_expired_events_task_registered():
    """The purge_expired_events task should be registered with the correct name."""
    assert purge_expired_events.name == "osint.purge_expired_events"


def test_purge_expired_events_task_max_retries():
    """The purge_expired_events task should have max_retries=3."""
    assert purge_expired_events.max_retries == 3


def test_purge_expired_events_is_bound():
    """The purge_expired_events task should be a bound task (bind=True)."""
    assert purge_expired_events.__bound__ is True


# ---------------------------------------------------------------------------
# Retention thresholds
# ---------------------------------------------------------------------------


def test_ephemeral_threshold_30_days():
    """Ephemeral events should be purged after 30 days."""
    assert RETENTION_THRESHOLDS["ephemeral"] == timedelta(days=30)


def test_standard_threshold_1_year():
    """Standard events should be purged after 1 year (365 days)."""
    assert RETENTION_THRESHOLDS["standard"] == timedelta(days=365)


def test_evidentiary_never_purged():
    """Evidentiary events should never be purged (threshold is None)."""
    assert RETENTION_THRESHOLDS["evidentiary"] is None


# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------


def test_beat_schedule_includes_retention():
    """The retention purge task should be in the beat schedule."""
    from osint_core.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "purge-expired-events-daily" in schedule
    entry = schedule["purge-expired-events-daily"]
    assert entry["task"] == "osint.purge_expired_events"


def test_beat_schedule_runs_at_0300():
    """The retention purge should be scheduled daily at 03:00 (app timezone)."""
    from celery.schedules import crontab

    from osint_core.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["purge-expired-events-daily"]
    sched = entry["schedule"]
    assert isinstance(sched, crontab)
    assert sched.hour == {3}
    assert sched.minute == {0}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_scalars(values: list[Any]) -> MagicMock:
    """Create a mock result with scalars().all() returning values."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = values
    return mock_result


def _make_mock_db(
    plan_version_ids: list[uuid.UUID] | None = None,
    event_id_batches: list[list[uuid.UUID]] | None = None,
) -> AsyncMock:
    """Build an AsyncMock DB session for retention tests.

    Args:
        plan_version_ids: IDs returned by the plan_version query.
        event_id_batches: Successive batches of event IDs returned by event queries.
            The last batch should be empty to signal completion.
    """
    pv_ids = plan_version_ids or []
    batches = event_id_batches or [[]]

    # Track call count to return different batches
    call_idx = {"execute": 0}
    pv_result = _make_mock_scalars(pv_ids)

    async def mock_execute(stmt: Any) -> Any:
        idx = call_idx["execute"]
        call_idx["execute"] += 1

        if idx == 0:
            # First call: plan_version IDs
            return pv_result

        # Subsequent calls alternate between select (event IDs) and delete
        # Select queries return event batches; deletes return MagicMock
        batch_idx = (idx - 1) // 2  # 1 select + 1 delete per batch cycle
        step_in_cycle = (idx - 1) % 2

        if step_in_cycle == 0:
            # Event ID select
            if batch_idx < len(batches):
                return _make_mock_scalars(batches[batch_idx])
            return _make_mock_scalars([])

        # Delete operations
        return MagicMock()

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=mock_execute)
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    return mock_db


# ---------------------------------------------------------------------------
# _purge_events_by_retention_class
# ---------------------------------------------------------------------------


class TestPurgeEventsByRetentionClass:
    """Tests for the per-class purge logic."""

    @pytest.mark.asyncio
    async def test_no_plan_versions_returns_zero(self):
        """When no plan versions match, no events are deleted."""
        mock_db = _make_mock_db(plan_version_ids=[], event_id_batches=[[]])

        with patch("osint_core.workers.retention.async_session", return_value=mock_db):
            purged_ids: list[str] = []
            count = await _purge_events_by_retention_class(
                "ephemeral", datetime.now(UTC), purged_ids,
            )

        assert count == 0
        assert purged_ids == []

    @pytest.mark.asyncio
    async def test_deletes_expired_events(self):
        """Expired events should be deleted and their IDs collected."""
        pv_id = uuid.uuid4()
        event_ids = [uuid.uuid4(), uuid.uuid4()]
        mock_db = _make_mock_db(
            plan_version_ids=[pv_id],
            event_id_batches=[event_ids, []],
        )

        with patch("osint_core.workers.retention.async_session", return_value=mock_db):
            purged_ids: list[str] = []
            count = await _purge_events_by_retention_class(
                "ephemeral", datetime.now(UTC), purged_ids,
            )

        assert count == 2
        assert len(purged_ids) == 2
        # Verify commit was called
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_handles_multiple_batches(self):
        """Multiple batches of events should all be deleted."""
        pv_id = uuid.uuid4()
        batch1 = [uuid.uuid4() for _ in range(3)]
        batch2 = [uuid.uuid4() for _ in range(2)]
        mock_db = _make_mock_db(
            plan_version_ids=[pv_id],
            event_id_batches=[batch1, batch2, []],
        )

        with patch("osint_core.workers.retention.async_session", return_value=mock_db):
            purged_ids: list[str] = []
            count = await _purge_events_by_retention_class(
                "standard", datetime.now(UTC), purged_ids,
            )

        assert count == 5
        assert len(purged_ids) == 5


# ---------------------------------------------------------------------------
# _purge_expired_events_async — evidentiary never deleted
# ---------------------------------------------------------------------------


class TestPurgeExpiredEventsAsync:
    """Tests for the main async purge orchestration."""

    @pytest.mark.asyncio
    async def test_evidentiary_events_never_deleted(self):
        """Evidentiary events must never be purged regardless of age."""
        mock_db = _make_mock_db(plan_version_ids=[], event_id_batches=[[]])

        with (
            patch("osint_core.workers.retention.async_session", return_value=mock_db),
            patch(
                "osint_core.workers.retention._purge_events_by_retention_class",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_purge,
            patch(
                "osint_core.workers.retention._remove_qdrant_vectors",
                return_value=0,
            ),
            patch(
                "osint_core.workers.retention._create_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            await _purge_expired_events_async()

        # _purge_events_by_retention_class should only be called for
        # ephemeral and standard, never evidentiary
        called_classes = [c.args[0] for c in mock_purge.call_args_list]
        assert "evidentiary" not in called_classes
        assert "ephemeral" in called_classes
        assert "standard" in called_classes

    @pytest.mark.asyncio
    async def test_creates_audit_log(self):
        """An audit log entry should be created after each purge run."""
        with (
            patch(
                "osint_core.workers.retention._purge_events_by_retention_class",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "osint_core.workers.retention._remove_qdrant_vectors",
                return_value=0,
            ),
            patch(
                "osint_core.workers.retention._create_audit_log",
                new_callable=AsyncMock,
            ) as mock_audit,
        ):
            await _purge_expired_events_async()

        mock_audit.assert_awaited_once()
        args = mock_audit.call_args
        assert isinstance(args[0][0], datetime)  # run_time
        assert isinstance(args[0][1], int)  # total_deleted
        assert isinstance(args[0][2], dict)  # deleted_by_class

    @pytest.mark.asyncio
    async def test_result_structure(self):
        """The result dict should contain expected keys."""
        with (
            patch(
                "osint_core.workers.retention._purge_events_by_retention_class",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "osint_core.workers.retention._remove_qdrant_vectors",
                return_value=3,
            ),
            patch(
                "osint_core.workers.retention._create_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            result = await _purge_expired_events_async()

        assert result["status"] == "ok"
        assert result["total_deleted"] == 10  # 5 ephemeral + 5 standard
        assert "ephemeral" in result["deleted_by_class"]
        assert "standard" in result["deleted_by_class"]
        assert result["qdrant_removed"] == 3


# ---------------------------------------------------------------------------
# _remove_qdrant_vectors
# ---------------------------------------------------------------------------


class TestRemoveQdrantVectors:
    """Tests for Qdrant vector cleanup."""

    def test_empty_event_ids_returns_zero(self):
        """No Qdrant calls when event_ids is empty."""
        assert _remove_qdrant_vectors([]) == 0

    def test_removes_vectors_by_deterministic_ids(self):
        """Qdrant points are deleted using UUID5-derived IDs."""
        import sys

        event_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        mock_client = MagicMock()

        # Build a lightweight stand-in for PointIdsList so the import
        # inside the try-block always succeeds, even when qdrant-client
        # is not installed in the test environment.
        class FakePointIdsList:
            def __init__(self, **kw: Any) -> None:
                self.__dict__.update(kw)

        # Ensure qdrant_client.models is importable even without the package
        fake_models = MagicMock()
        fake_models.PointIdsList = FakePointIdsList
        saved = {
            k: sys.modules.get(k)
            for k in ("qdrant_client", "qdrant_client.models")
        }
        sys.modules.setdefault("qdrant_client", MagicMock())
        sys.modules["qdrant_client.models"] = fake_models

        try:
            with (
                patch("osint_core.services.vectorize.get_qdrant", return_value=mock_client),
                patch("osint_core.config.settings") as mock_settings,
            ):
                mock_settings.qdrant_collection = "osint-events"
                result = _remove_qdrant_vectors(event_ids)
        finally:
            # Restore original module state
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        assert result == 2
        mock_client.delete.assert_called_once()
        call_kwargs = mock_client.delete.call_args
        assert call_kwargs[1]["collection_name"] == "osint-events"
        # Verify deterministic UUID5 derivation
        expected_ids = [
            str(uuid.uuid5(uuid.NAMESPACE_URL, eid)) for eid in event_ids
        ]
        selector = call_kwargs[1]["points_selector"]
        assert selector.points == expected_ids

    def test_qdrant_failure_returns_zero(self):
        """Qdrant failures are logged but don't raise."""
        with patch(
            "osint_core.services.vectorize.get_qdrant",
            side_effect=Exception("connection refused"),
        ):
            result = _remove_qdrant_vectors(["some-id"])

        assert result == 0


# ---------------------------------------------------------------------------
# _create_audit_log
# ---------------------------------------------------------------------------


class TestCreateAuditLog:
    """Tests for audit log creation."""

    @pytest.mark.asyncio
    async def test_creates_audit_entry(self):
        """An AuditLog record should be created with correct fields."""
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        now = datetime.now(UTC)
        deleted_by_class = {"ephemeral": 10, "standard": 5}

        with patch("osint_core.workers.retention.async_session", return_value=mock_db):
            await _create_audit_log(now, 15, deleted_by_class, 12)

        mock_db.add.assert_called_once()
        entry = mock_db.add.call_args[0][0]
        assert entry.action == "retention_purge"
        assert entry.actor == "system"
        assert entry.resource_type == "event"
        assert entry.details["total_deleted"] == 15
        assert entry.details["deleted_by_class"] == deleted_by_class
        assert entry.details["qdrant_removed"] == 12
        mock_db.commit.assert_awaited_once()
