"""Tests for NLP enrichment task."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from osint_core.workers.nlp_enrich import (
    _enrich_event_async,
    _validate_attack_techniques,
)


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
        # When LLM doesn't return attack_techniques, metadata should have empty list
        assert event.metadata_["attack_techniques"] == []


@pytest.mark.asyncio
async def test_generates_summary_even_when_source_summary_exists():
    """NLP summary must be set even when the event already has a source summary (e.g. RSS).

    Regression test for issue #107: the old code had
    ``if not event.summary and result.get("summary")`` which skipped NLP
    summary assignment when a source summary already existed.
    """
    event = MagicMock()
    event.id = "event-rss"
    event.title = "Austin bombing suspect identified"
    event.summary = "Police have identified the suspect in the Austin bombing."
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor terror threats"},
        "keywords": ["bombing"],
    }
    event.metadata_ = {}
    event.plan_version_id = "plan-uuid"

    vllm_response = {
        "summary": "Austin bombing suspect has been identified by police.",
        "relevance": "relevant",
        "entities": [{"name": "Austin", "type": "location"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-rss")
    assert result["status"] == "enriched"
    assert event.nlp_summary == "Austin bombing suspect has been identified by police."
    assert event.nlp_relevance == "relevant"


@pytest.mark.asyncio
async def test_nlp_disabled_when_plan_version_missing():
    """When event has no plan_version, nlp_enabled defaults to False
    and task returns nlp_disabled."""
    event = MagicMock()
    event.id = "event-no-plan"
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = None
    event.plan_version_id = "some-uuid"

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-no-plan")
        assert result["status"] == "nlp_disabled"


@pytest.mark.asyncio
async def test_stores_attack_techniques_in_metadata():
    """ATT&CK technique IDs from vLLM response are stored in event.metadata_."""
    event = MagicMock()
    event.id = "event-456"
    event.title = "Phishing campaign targeting finance sector"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor phishing campaigns"},
        "keywords": ["phishing"],
    }
    event.metadata_ = {}

    vllm_response = {
        "summary": "A phishing campaign targets the finance sector.",
        "relevance": "relevant",
        "entities": [{"name": "finance sector", "type": "organization"}],
        "attack_techniques": [
            {"id": "T1566", "name": "Phishing"},
            {"id": "T1071", "name": "Application Layer Protocol"},
        ],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-456")
        assert result["status"] == "enriched"
        techniques = event.metadata_["attack_techniques"]
        assert len(techniques) == 2
        assert techniques[0] == {"id": "T1566", "name": "Phishing"}
        assert techniques[1] == {"id": "T1071", "name": "Application Layer Protocol"}


@pytest.mark.asyncio
async def test_graceful_handling_missing_attack_techniques():
    """When LLM omits attack_techniques, metadata should get an empty list."""
    event = MagicMock()
    event.id = "event-789"
    event.title = "General news article"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "General monitoring"},
        "keywords": [],
    }
    event.metadata_ = {"existing_key": "value"}

    vllm_response = {
        "summary": "A general news article.",
        "relevance": "irrelevant",
        "entities": [],
        # No attack_techniques key at all
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-789")
        assert result["status"] == "enriched"
        # Existing metadata preserved
        assert event.metadata_["existing_key"] == "value"
        # attack_techniques defaults to empty list
        assert event.metadata_["attack_techniques"] == []


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


class TestValidateAttackTechniques:
    """Tests for _validate_attack_techniques helper."""

    def test_valid_techniques(self):
        raw = [{"id": "T1566", "name": "Phishing"}, {"id": "T1190", "name": "Exploit"}]
        result = _validate_attack_techniques(raw)
        assert len(result) == 2
        assert result[0] == {"id": "T1566", "name": "Phishing"}
        assert result[1] == {"id": "T1190", "name": "Exploit"}

    def test_returns_empty_for_none(self):
        assert _validate_attack_techniques(None) == []

    def test_returns_empty_for_string(self):
        assert _validate_attack_techniques("not a list") == []

    def test_skips_non_dict_items(self):
        raw = [{"id": "T1566", "name": "Phishing"}, "invalid", 42]
        result = _validate_attack_techniques(raw)
        assert len(result) == 1
        assert result[0]["id"] == "T1566"

    def test_skips_items_without_id(self):
        raw = [{"name": "Phishing"}, {"id": "", "name": "Empty ID"}]
        result = _validate_attack_techniques(raw)
        assert len(result) == 0

    def test_missing_name_defaults_to_empty_string(self):
        raw = [{"id": "T1566"}]
        result = _validate_attack_techniques(raw)
        assert len(result) == 1
        assert result[0] == {"id": "T1566", "name": ""}

    def test_non_string_name_defaults_to_empty_string(self):
        raw = [{"id": "T1566", "name": 123}]
        result = _validate_attack_techniques(raw)
        assert result[0] == {"id": "T1566", "name": ""}

    def test_empty_list(self):
        assert _validate_attack_techniques([]) == []


@respx.mock
@pytest.mark.asyncio
async def test_call_vllm_includes_attack_techniques_in_system_prompt():
    """The vLLM system message must include ATT&CK technique instructions."""
    content = json.dumps({
        "summary": "s", "relevance": "relevant",
        "entities": [], "attack_techniques": [],
    })
    vllm_response = {
        "choices": [{"message": {"content": content}}]
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
    assert "attack_techniques" in messages[0]["content"]
    assert "MITRE ATT&CK" in messages[0]["content"]
    assert "T1566" in messages[0]["content"]


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
