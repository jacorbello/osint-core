"""Tests for the audit logging service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from osint_core.models.audit import AuditLog
from osint_core.services.audit import create_audit_entry, list_audit_entries


def _make_audit_log(**overrides) -> AuditLog:
    """Create an AuditLog instance with sensible defaults for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "action": "test.action",
        "actor": "user-sub-123",
        "actor_username": "testuser",
        "actor_roles": ["admin"],
        "resource_type": "event",
        "resource_id": str(uuid.uuid4()),
        "details": {"key": "value"},
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    # Use the constructor — SQLAlchemy instruments it properly
    log = AuditLog(
        action=defaults["action"],
        actor=defaults.get("actor"),
        actor_username=defaults.get("actor_username"),
        actor_roles=defaults.get("actor_roles"),
        resource_type=defaults.get("resource_type"),
        resource_id=defaults.get("resource_id"),
        details=defaults.get("details", {}),
    )
    # Set id and created_at manually after construction
    log.id = defaults["id"]
    log.created_at = defaults["created_at"]
    return log


@pytest.mark.asyncio()
async def test_create_audit_entry():
    """create_audit_entry should add an AuditLog to the session and flush."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    entry = await create_audit_entry(
        db,
        action="event.created",
        actor="user-sub-123",
        actor_username="alastar",
        actor_roles=["admin", "analyst"],
        resource_type="event",
        resource_id="abc-123",
        details={"source_id": "cisa_kev"},
    )

    db.add.assert_called_once()
    db.flush.assert_awaited_once()

    assert isinstance(entry, AuditLog)
    assert entry.action == "event.created"
    assert entry.actor == "user-sub-123"
    assert entry.actor_username == "alastar"
    assert entry.actor_roles == ["admin", "analyst"]
    assert entry.resource_type == "event"
    assert entry.resource_id == "abc-123"
    assert entry.details == {"source_id": "cisa_kev"}


@pytest.mark.asyncio()
async def test_create_audit_entry_defaults():
    """create_audit_entry should use empty dict for details if not provided."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    entry = await create_audit_entry(db, action="system.startup")

    assert entry.actor is None
    assert entry.actor_username is None
    assert entry.actor_roles is None
    assert entry.resource_type is None
    assert entry.resource_id is None
    assert entry.details == {}


@pytest.mark.asyncio()
async def test_list_audit_entries():
    """list_audit_entries should return entries ordered by created_at desc."""
    entry1 = _make_audit_log(action="event.created")
    entry2 = _make_audit_log(action="alert.acked")

    # Mock scalars().all() chain
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [entry2, entry1]

    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    # Mock count result
    count_result_mock = MagicMock()
    count_result_mock.scalar_one.return_value = 2

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_mock, count_result_mock])

    entries, total = await list_audit_entries(db, limit=50, offset=0)

    assert len(entries) == 2
    assert total == 2
    assert entries[0].action == "alert.acked"
    assert entries[1].action == "event.created"


@pytest.mark.asyncio()
async def test_list_audit_entries_with_action_filter():
    """list_audit_entries with action filter should pass it to the query."""
    entry = _make_audit_log(action="event.created")

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [entry]

    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    count_result_mock = MagicMock()
    count_result_mock.scalar_one.return_value = 1

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_mock, count_result_mock])

    entries, total = await list_audit_entries(db, action="event.created")

    assert len(entries) == 1
    assert total == 1
    assert entries[0].action == "event.created"


@pytest.mark.asyncio()
async def test_list_audit_entries_empty():
    """list_audit_entries should handle empty results."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []

    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock

    count_result_mock = MagicMock()
    count_result_mock.scalar_one.return_value = 0

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[result_mock, count_result_mock])

    entries, total = await list_audit_entries(db)

    assert entries == []
    assert total == 0
