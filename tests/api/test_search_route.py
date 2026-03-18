"""Tests for semantic search route."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from osint_core.api.routes.search import search_semantic
from osint_core.schemas.event import EventSearchList
from tests.helpers import make_user, run_async


def _make_event(event_id: uuid.UUID | None = None) -> MagicMock:
    """Return a mock Event ORM object with Pydantic-compatible field values."""
    e = MagicMock()
    e.id = event_id or uuid.uuid4()
    e.event_type = "test"
    e.source_id = "test-source"
    e.title = None
    e.summary = None
    e.raw_excerpt = None
    e.occurred_at = None
    from datetime import UTC, datetime
    e.ingested_at = datetime(2026, 1, 1, tzinfo=UTC)
    e.score = None
    e.severity = None
    e.dedupe_fingerprint = "fp"
    e.plan_version_id = None
    e.latitude = None
    e.longitude = None
    e.country_code = None
    e.region = None
    e.source_category = None
    e.metadata_ = {}
    return e


def _make_db(events: list[MagicMock]) -> AsyncMock:
    """Return an AsyncSession mock whose execute() yields the given events."""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = events
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@patch("osint_core.api.routes.search.search_similar")
def test_semantic_search_returns_events(mock_search_similar):
    """Route fetches events from Postgres and returns them in score order."""
    event_id = uuid.uuid4()
    mock_search_similar.return_value = [
        {"id": "point-1", "score": 0.91, "payload": {"event_id": str(event_id)}},
    ]

    event = _make_event(event_id)
    db = _make_db([event])

    result = run_async(
        search_semantic(
            q="cyberattack on infrastructure",
            limit=10,
            score_threshold=0.5,
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, EventSearchList)
    assert result.retrieval_mode == "semantic"
    assert len(result.items) == 1
    assert result.items[0].id == event_id
    mock_search_similar.assert_called_once_with(
        "cyberattack on infrastructure", limit=10, score_threshold=0.5
    )


@patch("osint_core.api.routes.search.search_similar")
def test_semantic_search_preserves_score_order(mock_search_similar):
    """Events are returned in Qdrant score order (highest first)."""
    id_high = uuid.uuid4()
    id_low = uuid.uuid4()

    mock_search_similar.return_value = [
        {"id": "p1", "score": 0.95, "payload": {"event_id": str(id_high)}},
        {"id": "p2", "score": 0.60, "payload": {"event_id": str(id_low)}},
    ]

    event_high = _make_event(id_high)
    event_low = _make_event(id_low)
    # DB returns in arbitrary order
    db = _make_db([event_low, event_high])

    result = run_async(
        search_semantic(
            q="ransomware attack",
            limit=10,
            score_threshold=0.5,
            db=db,
            current_user=make_user(),
        )
    )

    assert result.items[0].id == id_high
    assert result.items[1].id == id_low


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@patch("osint_core.api.routes.search.search_similar")
def test_semantic_search_no_qdrant_hits(mock_search_similar):
    """Returns empty list when Qdrant has no hits above threshold."""
    mock_search_similar.return_value = []
    db = _make_db([])

    result = run_async(
        search_semantic(
            q="nothing matches this",
            limit=20,
            score_threshold=0.5,
            db=db,
            current_user=make_user(),
        )
    )

    assert result.items == []
    assert result.page.total == 0
    db.execute.assert_not_called()


@patch("osint_core.api.routes.search.search_similar")
def test_semantic_search_skips_invalid_event_ids(mock_search_similar):
    """Hits with malformed event_id in payload are silently skipped."""
    valid_id = uuid.uuid4()
    mock_search_similar.return_value = [
        {"id": "p1", "score": 0.88, "payload": {"event_id": "not-a-uuid"}},
        {"id": "p2", "score": 0.75, "payload": {"event_id": str(valid_id)}},
    ]

    event = _make_event(valid_id)
    db = _make_db([event])

    result = run_async(
        search_semantic(
            q="query",
            limit=10,
            score_threshold=0.5,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    assert result.items[0].id == valid_id


@patch("osint_core.api.routes.search.search_similar")
def test_semantic_search_event_deleted_from_postgres(mock_search_similar):
    """Qdrant hits whose events no longer exist in Postgres are omitted gracefully."""
    ghost_id = uuid.uuid4()
    mock_search_similar.return_value = [
        {"id": "p1", "score": 0.80, "payload": {"event_id": str(ghost_id)}},
    ]
    # Postgres returns nothing (event was deleted)
    db = _make_db([])

    result = run_async(
        search_semantic(
            q="ghost event",
            limit=10,
            score_threshold=0.5,
            db=db,
            current_user=make_user(),
        )
    )

    assert result.items == []
    assert result.page.total == 0
