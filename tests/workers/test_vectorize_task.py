"""Tests for the vectorize_event_task Celery task."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.enrich import _EventNotFoundError, _vectorize_event_async

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    event_id: str | None = None,
    title: str = "Apache RCE vulnerability",
    summary: str = "Critical RCE discovered in Apache 2.4",
    source_id: str = "cisa-kev",
    event_type: str = "cisa_kev",
    severity: str = "critical",
    occurred_at: datetime | None = None,
) -> MagicMock:
    event = MagicMock()
    event.id = uuid.UUID(event_id) if event_id else uuid.uuid4()
    event.title = title
    event.summary = summary
    event.source_id = source_id
    event.event_type = event_type
    event.severity = severity
    event.occurred_at = occurred_at or datetime(2026, 3, 1, tzinfo=UTC)
    return event


# ---------------------------------------------------------------------------
# _vectorize_event_async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vectorize_event_async_success():
    """Successful upsert returns event_id, vector_id, and status=ok."""
    event_id = str(uuid.uuid4())
    event = _make_event(event_id=event_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=event)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("osint_core.workers.enrich.async_session", return_value=mock_db),
        patch("osint_core.workers.enrich.upsert_event"),
    ):
        result = await _vectorize_event_async(event_id)

    assert result["event_id"] == event_id
    assert result["status"] == "ok"
    assert "vector_id" in result
    # vector_id is a deterministic uuid5 from event_id
    expected_vid = str(uuid.uuid5(uuid.NAMESPACE_URL, event_id))
    assert result["vector_id"] == expected_vid


@pytest.mark.asyncio
async def test_vectorize_event_async_missing_event():
    """Raises _EventNotFoundError when event is not in the database."""
    event_id = str(uuid.uuid4())

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("osint_core.workers.enrich.async_session", return_value=mock_db),
        pytest.raises(_EventNotFoundError),
    ):
        await _vectorize_event_async(event_id)


@pytest.mark.asyncio
async def test_vectorize_event_async_calls_upsert_with_correct_text():
    """upsert_event is called with combined title + summary text."""
    event_id = str(uuid.uuid4())
    event = _make_event(
        event_id=event_id,
        title="Flood warning",
        summary="Severe flooding in region X",
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=event)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    captured: dict = {}

    def _capture_upsert(eid, text, payload):
        captured["event_id"] = eid
        captured["text"] = text
        captured["payload"] = payload

    with (
        patch("osint_core.workers.enrich.async_session", return_value=mock_db),
        patch("osint_core.workers.enrich.upsert_event", side_effect=_capture_upsert),
    ):
        await _vectorize_event_async(event_id)

    assert captured["event_id"] == event_id
    assert "Flood warning" in captured["text"]
    assert "Severe flooding in region X" in captured["text"]
    assert captured["payload"]["source_id"] == "cisa-kev"
    assert captured["payload"]["severity"] == "critical"


@pytest.mark.asyncio
async def test_vectorize_event_async_payload_metadata():
    """Payload includes source, event_type, severity, occurred_at, title."""
    event_id = str(uuid.uuid4())
    occurred = datetime(2026, 1, 15, tzinfo=UTC)
    event = _make_event(
        event_id=event_id,
        title="Test event",
        summary="Test summary",
        source_id="gdelt",
        event_type="gdelt",
        severity="high",
        occurred_at=occurred,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=event)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    payloads: list[dict] = []

    def _capture(eid, text, payload):
        payloads.append(payload)

    with (
        patch("osint_core.workers.enrich.async_session", return_value=mock_db),
        patch("osint_core.workers.enrich.upsert_event", side_effect=_capture),
    ):
        await _vectorize_event_async(event_id)

    assert len(payloads) == 1
    p = payloads[0]
    assert p["source_id"] == "gdelt"
    assert p["event_type"] == "gdelt"
    assert p["severity"] == "high"
    assert p["occurred_at"] == occurred.isoformat()
    assert p["title"] == "Test event"


# ---------------------------------------------------------------------------
# vectorize_event_task (Celery task) — retry behavior
# ---------------------------------------------------------------------------


def _mock_loop(return_value=None, side_effect=None):
    """Return a mock event loop whose run_until_complete behaves as specified."""
    loop = MagicMock()
    if side_effect is not None:
        loop.run_until_complete.side_effect = side_effect
    else:
        loop.run_until_complete.return_value = return_value
    return loop


def test_vectorize_event_task_returns_ok_on_success():
    """Task returns status=ok for a valid event."""
    event_id = str(uuid.uuid4())
    expected_vid = str(uuid.uuid5(uuid.NAMESPACE_URL, event_id))
    mock_result = {"event_id": event_id, "vector_id": expected_vid, "status": "ok"}

    with patch(
        "osint_core.workers.enrich.asyncio.new_event_loop",
        return_value=_mock_loop(return_value=mock_result),
    ):
        from osint_core.workers.enrich import vectorize_event_task

        result = vectorize_event_task(event_id)

    assert result["status"] == "ok"
    assert result["event_id"] == event_id


def test_vectorize_event_task_returns_not_found_for_missing_event():
    """Task returns status=not_found without retrying for missing events."""
    event_id = str(uuid.uuid4())

    with patch(
        "osint_core.workers.enrich.asyncio.new_event_loop",
        return_value=_mock_loop(side_effect=_EventNotFoundError("no event")),
    ):
        from osint_core.workers.enrich import vectorize_event_task

        result = vectorize_event_task(event_id)

    assert result["status"] == "not_found"
    assert result["event_id"] == event_id


def test_vectorize_event_task_retries_on_qdrant_unavailable():
    """Task schedules a retry on transient Qdrant/DB errors."""
    import celery.exceptions

    event_id = str(uuid.uuid4())

    mock_self = MagicMock()
    mock_self.request.retries = 0
    mock_self.retry = MagicMock(side_effect=celery.exceptions.Retry())

    with patch(
        "osint_core.workers.enrich.asyncio.new_event_loop",
        return_value=_mock_loop(side_effect=ConnectionRefusedError("Qdrant unavailable")),
    ):
        from osint_core.workers.enrich import vectorize_event_task

        with pytest.raises(celery.exceptions.Retry):
            vectorize_event_task.run.__func__(mock_self, event_id)  # type: ignore[attr-defined]

    mock_self.retry.assert_called_once()
    call_kwargs = mock_self.retry.call_args.kwargs
    assert call_kwargs["countdown"] == 30  # 2**0 * 30
