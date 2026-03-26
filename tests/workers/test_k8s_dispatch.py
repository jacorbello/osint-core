"""Tests for entity enrichment in k8s_dispatch."""
from __future__ import annotations
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from osint_core.workers.k8s_dispatch import _enrich_entities_async

def _mock_event(title="Test Event", summary="Summary"):
    event = SimpleNamespace(id=uuid.uuid4(), title=title, summary=summary, raw_excerpt="https://example.com", entities=[])
    return event

def _mock_entity(name="Austin", ent_type="LOCATION"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, entity_type=ent_type)

@pytest.mark.asyncio
async def test_entity_linking_uses_materialized_list():
    event = _mock_event()
    entity_a = _mock_entity("Austin", "LOCATION")
    entity_b = _mock_entity("FBI", "ORG")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = event
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.return_value = mock_ctx
    with (
        patch("osint_core.workers.k8s_dispatch.async_session", mock_session),
        patch("osint_core.workers.k8s_dispatch.extract_entities", return_value=[{"name": "Austin", "type": "LOCATION"}, {"name": "FBI", "type": "ORG"}]),
        patch("osint_core.workers.k8s_dispatch._upsert_entity", new_callable=AsyncMock, side_effect=[entity_a, entity_b]),
    ):
        result = await _enrich_entities_async(str(event.id))
    assert result["entities_found"] == 2
    assert result["status"] == "ok"

@pytest.mark.asyncio
async def test_entity_linking_deduplicates():
    event = _mock_event()
    entity = _mock_entity("Austin", "LOCATION")
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = event
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.return_value = mock_ctx
    with (
        patch("osint_core.workers.k8s_dispatch.async_session", mock_session),
        patch("osint_core.workers.k8s_dispatch.extract_entities", return_value=[{"name": "Austin", "type": "LOCATION"}, {"name": "Austin", "type": "LOCATION"}]),
        patch("osint_core.workers.k8s_dispatch._upsert_entity", new_callable=AsyncMock, return_value=entity),
    ):
        result = await _enrich_entities_async(str(event.id))
    assert len(event.entities) == 1
