"""Tests for watch API routes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import Response

from osint_core.api.routes import watches
from osint_core.models.watch import Watch
from tests.helpers import make_request, make_user, run_async


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_single_result(item):
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    return result


def _make_watch(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "name": "test-watch",
        "watch_type": "dynamic",
        "status": "active",
        "region": "Eastern Europe",
        "country_codes": ["UKR", "RUS"],
        "bounding_box": None,
        "keywords": ["NATO"],
        "source_filter": None,
        "severity_threshold": "low",
        "plan_id": None,
        "ttl_hours": None,
        "expires_at": None,
        "promoted_at": None,
        "created_by": "manual",
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Watch)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


class TestWatchRoutes:
    def test_create_watch_returns_location(self):
        db = _mock_db()
        watch = _make_watch(name="new-watch")
        response = Response()

        async def refresh(obj):
            for key, value in {
                "id": watch.id,
                "name": watch.name,
                "watch_type": watch.watch_type,
                "status": watch.status,
                "region": watch.region,
                "country_codes": watch.country_codes,
                "bounding_box": watch.bounding_box,
                "keywords": watch.keywords,
                "source_filter": watch.source_filter,
                "severity_threshold": watch.severity_threshold,
                "plan_id": watch.plan_id,
                "ttl_hours": watch.ttl_hours,
                "expires_at": watch.expires_at,
                "promoted_at": watch.promoted_at,
                "created_by": "admin",
                "created_at": watch.created_at,
            }.items():
                setattr(obj, key, value)

        db.refresh = refresh
        result = run_async(
            watches.create_watch(
                body=watches.WatchCreateRequest(
                    name="new-watch",
                    region="Eastern Europe",
                    severity_threshold="low",
                ),
                request=make_request("/api/v1/watches", method="POST"),
                response=response,
                db=db,
                current_user=make_user(),
            )
        )
        assert response.headers["Location"].endswith(str(watch.id))
        assert result.name == "new-watch"

    def test_get_watch_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        result = run_async(
            watches.get_watch(
                uuid.uuid4(),
                request=make_request("/api/v1/watches/missing"),
                db=db,
                current_user=make_user(),
            )
        )
        assert result.status_code == 404
        assert json.loads(result.body)["code"] == "not_found"

    def test_delete_watch_returns_204(self):
        watch = _make_watch()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(watch))
        result = run_async(
            watches.delete_watch(
                watch.id,
                request=make_request(f"/api/v1/watches/{watch.id}", method="DELETE"),
                db=db,
                current_user=make_user(),
            )
        )
        assert result is None
        db.delete.assert_awaited_once()

    def test_update_watch_clears_expiry_when_ttl_removed(self):
        watch = _make_watch(ttl_hours=4, expires_at=datetime.now(UTC))
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(watch))
        db.refresh = AsyncMock()

        result = run_async(
            watches.update_watch(
                watch.id,
                body=watches.WatchUpdateRequest(ttl_hours=None),
                request=make_request(f"/api/v1/watches/{watch.id}", method="PATCH"),
                db=db,
                current_user=make_user(),
            )
        )
        assert result.expires_at is None
