"""Tests for watch API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from osint_core.api.deps import get_db
from osint_core.main import app
from osint_core.models.watch import Watch


def _mock_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _mock_scalars_result(items: list, total: int = None):
    """Create mock execute results for list queries (data + count)."""
    if total is None:
        total = len(items)

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items

    data_result = MagicMock()
    data_result.scalars.return_value = scalars_mock

    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    return [data_result, count_result]


def _mock_single_result(item):
    """Create mock execute result for single-item queries."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    return result


def _make_watch(**overrides) -> MagicMock:
    """Create a mock Watch."""
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
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


class TestWatchRoutes:
    """Tests for /api/v1/watches endpoints."""

    def test_list_watches_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/watches")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

        app.dependency_overrides.clear()

    def test_list_watches_with_items(self):
        watch = _make_watch()
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([watch], 1))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/watches")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "test-watch"

        app.dependency_overrides.clear()

    def test_create_watch(self):
        db = _mock_db()

        # After add + commit + refresh, return a mock watch
        watch_mock = _make_watch(name="new-watch")

        async def mock_refresh(obj):
            for k, v in {
                "id": watch_mock.id,
                "name": watch_mock.name,
                "watch_type": "dynamic",
                "status": "active",
                "region": "Eastern Europe",
                "country_codes": ["UKR"],
                "bounding_box": None,
                "keywords": None,
                "source_filter": None,
                "severity_threshold": "low",
                "plan_id": None,
                "ttl_hours": None,
                "expires_at": None,
                "promoted_at": None,
                "created_by": "manual",
                "created_at": watch_mock.created_at,
            }.items():
                setattr(obj, k, v)

        db.refresh = mock_refresh

        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(
            "/api/v1/watches",
            json={
                "name": "new-watch",
                "region": "Eastern Europe",
                "country_codes": ["UKR"],
                "severity_threshold": "low",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "new-watch"
        assert data["watch_type"] == "dynamic"
        assert data["status"] == "active"

        app.dependency_overrides.clear()

    def test_get_watch_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/watches/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_watch_route_registered(self):
        """Verify the watches route is registered."""
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        matching = [p for p in route_paths if p.startswith("/api/v1/watches")]
        assert len(matching) > 0, "No watch routes found"
