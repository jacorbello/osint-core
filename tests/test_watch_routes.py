"""Tests for watch API routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import Response
from starlette.requests import Request

from osint_core.api.middleware.auth import UserInfo
from osint_core.api.routes import watches
from osint_core.models.watch import Watch


def _run(awaitable):
    return asyncio.run(awaitable)


def _request(path: str, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


def _user() -> UserInfo:
    return UserInfo(sub="u-1", username="admin", roles=["admin"])


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
        result = _run(
            watches.create_watch(
                body=watches.WatchCreateRequest(name="new-watch", region="Eastern Europe", severity_threshold="low"),
                request=_request("/api/v1/watches", method="POST"),
                response=response,
                db=db,
                current_user=_user(),
            )
        )
        assert response.headers["Location"].endswith(str(watch.id))
        assert result.name == "new-watch"

    def test_get_watch_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        result = _run(
            watches.get_watch(
                uuid.uuid4(),
                request=_request("/api/v1/watches/missing"),
                db=db,
                current_user=_user(),
            )
        )
        assert result.status_code == 404
        assert json.loads(result.body)["code"] == "not_found"

    def test_delete_watch_returns_204(self):
        watch = _make_watch()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(watch))
        result = _run(
            watches.delete_watch(
                watch.id,
                request=_request(f"/api/v1/watches/{watch.id}", method="DELETE"),
                db=db,
                current_user=_user(),
            )
        )
        assert result is None
        db.delete.assert_awaited_once()
