"""Tests for NLP enrichment task."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.nlp_enrich import _enrich_event_async


def _mock_engine():
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


def _mock_session(event):
    session = AsyncMock()
    session.get = AsyncMock(return_value=event)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_skips_event_with_existing_nlp_data():
    event = MagicMock()
    event.nlp_relevance = "relevant"
    event.nlp_summary = "Already summarized"

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_generates_summary_for_empty():
    event = MagicMock()
    event.id = "event-123"
    event.title = "Bombing in downtown Austin"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor terror threats in Austin"},
        "keywords": ["bombing", "attack"],
    }
    event.metadata_ = {}

    llm_response = {
        "summary": "A bombing incident occurred in downtown Austin.",
        "relevance": "relevant",
        "entities": [{"name": "Austin", "type": "location"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_llm", return_value=llm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "enriched"
        assert event.nlp_summary == "A bombing incident occurred in downtown Austin."
        assert event.nlp_relevance == "relevant"


@pytest.mark.asyncio
async def test_fallback_on_llm_timeout():
    event = MagicMock()
    event.id = "event-123"
    event.title = "Some article"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "test"},
        "keywords": [],
    }
    event.metadata_ = {}

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_llm", side_effect=TimeoutError):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "fallback"
