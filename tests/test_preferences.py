"""Tests for user preference and saved search routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from osint_core.api.routes import preferences
from osint_core.models.user_preference import UserPreference
from osint_core.schemas.preference import (
    PreferenceResponse,
    PreferenceUpdateRequest,
    SavedSearchRequest,
    SavedSearchResponse,
)
from tests.helpers import make_request, make_user, run_async


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_single_result(item):
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    return result


def _make_preference(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "user_sub": "u-1",
        "notification_prefs": {},
        "saved_searches": [],
        "timezone": "UTC",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=UserPreference)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


# ── GET /preferences ──────────────────────────────────────────────


class TestGetPreferences:
    def test_returns_existing_preference(self):
        pref = _make_preference()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        result = run_async(preferences.get_preferences(db=db, current_user=user))

        assert isinstance(result, PreferenceResponse)
        assert result.user_sub == "u-1"
        assert result.timezone == "UTC"

    def test_creates_preference_if_absent(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))

        # After flush+refresh, the new pref should be accessible
        new_pref = _make_preference()
        db.refresh = AsyncMock(side_effect=lambda p: _apply_defaults(p, new_pref))

        user = make_user()
        run_async(preferences.get_preferences(db=db, current_user=user))

        db.add.assert_called_once()
        db.flush.assert_awaited_once()


# ── PUT /preferences ──────────────────────────────────────────────


class TestUpdatePreferences:
    def test_updates_timezone(self):
        pref = _make_preference()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        body = PreferenceUpdateRequest(timezone="America/New_York")
        run_async(
            preferences.update_preferences(body=body, db=db, current_user=user)
        )

        assert pref.timezone == "America/New_York"
        db.commit.assert_awaited_once()

    def test_updates_notification_prefs(self):
        pref = _make_preference()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        new_prefs = {"email": True, "slack": False}
        body = PreferenceUpdateRequest(notification_prefs=new_prefs)
        run_async(
            preferences.update_preferences(body=body, db=db, current_user=user)
        )

        assert pref.notification_prefs == new_prefs

    def test_skips_none_fields(self):
        pref = _make_preference(timezone="Europe/London")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        body = PreferenceUpdateRequest()
        run_async(
            preferences.update_preferences(body=body, db=db, current_user=user)
        )

        assert pref.timezone == "Europe/London"


# ── POST /saved-searches ─────────────────────────────────────────


class TestCreateSavedSearch:
    def test_creates_saved_search(self):
        pref = _make_preference(saved_searches=[])
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        body = SavedSearchRequest(
            name="My Search",
            query="malware",
            filters={"severity": "high"},
            alert_enabled=True,
        )
        result = run_async(
            preferences.create_saved_search(body=body, db=db, current_user=user)
        )

        assert isinstance(result, SavedSearchResponse)
        assert result.name == "My Search"
        assert result.query == "malware"
        assert result.alert_enabled is True
        assert len(pref.saved_searches) == 1


# ── GET /saved-searches ──────────────────────────────────────────


class TestListSavedSearches:
    def test_returns_empty_list(self):
        pref = _make_preference(saved_searches=[])
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        result = run_async(
            preferences.list_saved_searches(db=db, current_user=user)
        )

        assert result == []

    def test_returns_saved_searches(self):
        searches = [
            {
                "id": "s-1",
                "name": "Test",
                "query": "test",
                "filters": {},
                "alert_enabled": False,
                "created_at": "2026-03-20T00:00:00",
            }
        ]
        pref = _make_preference(saved_searches=searches)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()

        result = run_async(
            preferences.list_saved_searches(db=db, current_user=user)
        )

        assert len(result) == 1
        assert result[0].name == "Test"


# ── DELETE /saved-searches/{search_id} ───────────────────────────


class TestDeleteSavedSearch:
    def test_deletes_existing_search(self):
        searches = [
            {
                "id": "s-1",
                "name": "Test",
                "query": "test",
                "filters": {},
                "alert_enabled": False,
                "created_at": "2026-03-20T00:00:00",
            }
        ]
        pref = _make_preference(saved_searches=searches)
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()
        request = make_request("/api/v1/saved-searches/s-1", method="DELETE")

        result = run_async(
            preferences.delete_saved_search(
                search_id="s-1", request=request, db=db, current_user=user
            )
        )

        assert result is None
        assert len(pref.saved_searches) == 0
        db.commit.assert_awaited_once()

    def test_returns_404_for_unknown_search(self):
        pref = _make_preference(saved_searches=[])
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(pref))
        user = make_user()
        request = make_request("/api/v1/saved-searches/unknown", method="DELETE")

        result = run_async(
            preferences.delete_saved_search(
                search_id="unknown", request=request, db=db, current_user=user
            )
        )

        # Should return a JSONResponse with 404 status
        assert hasattr(result, "status_code")
        assert result.status_code == 404


# ── Helpers ──────────────────────────────────────────────────────


def _apply_defaults(target, source):
    """Copy attributes from source mock to target during db.refresh."""
    attrs = (
        "id", "user_sub", "notification_prefs", "saved_searches",
        "timezone", "created_at", "updated_at",
    )
    for attr in attrs:
        setattr(target, attr, getattr(source, attr))
