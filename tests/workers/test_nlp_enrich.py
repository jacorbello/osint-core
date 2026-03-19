"""Tests for NLP enrichment task."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

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

    vllm_response = {
        "summary": "A bombing incident occurred in downtown Austin.",
        "relevance": "relevant",
        "entities": [{"name": "Austin", "type": "location"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "enriched"
        assert event.nlp_summary == "A bombing incident occurred in downtown Austin."
        assert event.nlp_relevance == "relevant"


@pytest.mark.asyncio
async def test_fallback_on_vllm_timeout():
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
         patch("osint_core.workers.nlp_enrich._call_vllm", side_effect=TimeoutError):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "fallback"


class TestStripMarkdownFences:
    def test_plain_json_unchanged(self):
        from osint_core.workers.nlp_enrich import _strip_markdown_fences
        text = '{"summary": "test", "relevance": "relevant", "entities": []}'
        assert _strip_markdown_fences(text) == text

    def test_strips_json_code_fence(self):
        from osint_core.workers.nlp_enrich import _strip_markdown_fences
        text = '```json\n{"summary": "test", "relevance": "relevant"}\n```'
        result = _strip_markdown_fences(text)
        parsed = json.loads(result)
        assert parsed["summary"] == "test"

    def test_strips_bare_code_fence(self):
        from osint_core.workers.nlp_enrich import _strip_markdown_fences
        text = '```\n{"summary": "test"}\n```'
        result = _strip_markdown_fences(text)
        parsed = json.loads(result)
        assert parsed["summary"] == "test"

    def test_strips_whitespace_when_no_fences(self):
        from osint_core.workers.nlp_enrich import _strip_markdown_fences
        text = '  \n{"summary": "test"}\n  '
        result = _strip_markdown_fences(text)
        assert result == '{"summary": "test"}'

    def test_handles_fences_with_surrounding_text(self):
        from osint_core.workers.nlp_enrich import _strip_markdown_fences
        text = 'Here is the result:\n```json\n{"summary": "test"}\n```\nDone.'
        result = _strip_markdown_fences(text)
        parsed = json.loads(result)
        assert parsed["summary"] == "test"


@respx.mock
@pytest.mark.asyncio
async def test_call_vllm_includes_system_role():
    """The vLLM payload must include a system role message."""
    vllm_response = {
        "choices": [
            {"message": {"content": '{"summary":"s","relevance":"relevant","entities":[]}'}}
        ]
    }
    route = respx.post("http://localhost:8001/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=vllm_response),
    )
    from osint_core.workers.nlp_enrich import _call_vllm
    await _call_vllm("test prompt")
    sent = route.calls.last.request
    body = json.loads(sent.content)
    messages = body["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "JSON only" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "test prompt"


@respx.mock
@pytest.mark.asyncio
async def test_call_vllm_parses_markdown_wrapped_json():
    """vLLM sometimes wraps JSON in markdown code fences."""
    wrapped = '```json\n{"summary":"s","relevance":"relevant","entities":[]}\n```'
    vllm_response = {"choices": [{"message": {"content": wrapped}}]}
    respx.post("http://localhost:8001/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=vllm_response),
    )
    from osint_core.workers.nlp_enrich import _call_vllm
    result = await _call_vllm("test prompt")
    assert result["relevance"] == "relevant"
    assert result["summary"] == "s"
