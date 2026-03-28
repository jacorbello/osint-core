"""Tests for NLP enrichment task."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from osint_core.workers.nlp_enrich import (
    _enrich_event_async,
    _validate_attack_techniques,
    _validate_constitutional_fields,
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
    event.plan_version = MagicMock()
    event.plan_version.plan_id = "some-plan"
    event.plan_version.content = {"enrichment": {"nlp_enabled": True}}
    event.metadata_ = {"attack_techniques": [{"id": "T1566", "name": "Phishing"}]}

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_re_enriches_when_plan_switches_to_cal():
    """Events enriched under ATT&CK prompt get re-enriched when plan changes to CAL."""
    event = _make_cal_event()
    event.nlp_relevance = "relevant"
    event.nlp_summary = "Previously enriched summary."
    # Has ATT&CK metadata but no CAL metadata — should re-enrich
    event.metadata_ = {"attack_techniques": [{"id": "T1566", "name": "Phishing"}]}

    vllm_response = {
        "summary": "Re-enriched for CAL.",
        "relevance": "relevant",
        "entities": [],
        "constitutional_basis": ["1A-free-speech"],
        "lead_type": "incident",
        "institution": "UC Davis",
        "jurisdiction": "CA",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-cal-001")

    assert result["status"] == "enriched"
    assert event.metadata_["constitutional_basis"] == ["1A-free-speech"]
    assert "attack_techniques" not in event.metadata_


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
async def test_call_vllm_custom_system_message_and_max_tokens():
    """Custom system_message and max_tokens are forwarded in the payload."""
    content = json.dumps({
        "summary": "s", "relevance": "relevant",
        "entities": [], "constitutional_basis": [],
    })
    vllm_response = {"choices": [{"message": {"content": content}}]}
    route = respx.post("http://localhost:8001/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=vllm_response),
    )
    from osint_core.workers.nlp_enrich import _call_vllm
    custom_msg = "You are a constitutional rights analyst. Respond with JSON only."
    await _call_vllm("test prompt", system_message=custom_msg, max_tokens=800)
    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body["messages"][0]["content"] == custom_msg
    assert body["max_tokens"] == 800


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


# ---------------------------------------------------------------------------
# Constitutional classification tests
# ---------------------------------------------------------------------------


class TestValidateConstitutionalFields:
    """Tests for _validate_constitutional_fields helper."""

    def test_valid_fields(self):
        result = _validate_constitutional_fields({
            "constitutional_basis": ["1A-free-speech", "14A-due-process"],
            "lead_type": "incident",
            "institution": "UC Berkeley",
            "jurisdiction": "CA",
        })
        assert result["constitutional_basis"] == ["1A-free-speech", "14A-due-process"]
        assert result["lead_type"] == "incident"
        assert result["institution"] == "UC Berkeley"
        assert result["jurisdiction"] == "CA"

    def test_filters_invalid_constitutional_basis(self):
        result = _validate_constitutional_fields({
            "constitutional_basis": ["1A-free-speech", "INVALID", "parental-rights"],
        })
        assert result["constitutional_basis"] == ["1A-free-speech", "parental-rights"]

    def test_non_list_basis_returns_empty(self):
        result = _validate_constitutional_fields({
            "constitutional_basis": "1A-free-speech",
        })
        assert result["constitutional_basis"] == []

    def test_missing_basis_returns_empty(self):
        result = _validate_constitutional_fields({})
        assert result["constitutional_basis"] == []

    def test_invalid_lead_type_returns_none(self):
        result = _validate_constitutional_fields({"lead_type": "unknown"})
        assert result["lead_type"] is None

    def test_policy_lead_type(self):
        result = _validate_constitutional_fields({"lead_type": "policy"})
        assert result["lead_type"] == "policy"

    def test_empty_institution_returns_none(self):
        result = _validate_constitutional_fields({"institution": ""})
        assert result["institution"] is None

    def test_null_institution_returns_none(self):
        result = _validate_constitutional_fields({"institution": None})
        assert result["institution"] is None

    def test_invalid_jurisdiction_returns_none(self):
        result = _validate_constitutional_fields({"jurisdiction": "NY"})
        assert result["jurisdiction"] is None

    def test_valid_jurisdictions(self):
        for j in ("CA", "TX", "MN", "DC"):
            result = _validate_constitutional_fields({"jurisdiction": j})
            assert result["jurisdiction"] == j

    def test_normalizes_lowercase_jurisdiction(self):
        result = _validate_constitutional_fields({"jurisdiction": "ca"})
        assert result["jurisdiction"] == "CA"

    def test_normalizes_full_state_name(self):
        result = _validate_constitutional_fields({"jurisdiction": "California"})
        assert result["jurisdiction"] == "CA"

    def test_normalizes_texas(self):
        result = _validate_constitutional_fields({"jurisdiction": "texas"})
        assert result["jurisdiction"] == "TX"

    def test_normalizes_district_of_columbia(self):
        result = _validate_constitutional_fields({"jurisdiction": "District of Columbia"})
        assert result["jurisdiction"] == "DC"


def _make_cal_event():
    """Create a mock event associated with the CAL prospecting plan."""
    event = MagicMock()
    event.id = "event-cal-001"
    event.title = "Professor fired for classroom speech at UC Davis"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.plan_id = "cal-prospecting"
    event.plan_version.content = {
        "enrichment": {
            "nlp_enabled": True,
            "mission": "Identify constitutional rights violations at educational institutions.",
        },
        "keywords": ["free speech", "First Amendment", "campus speech"],
    }
    event.metadata_ = {}
    event.plan_version_id = "plan-uuid"
    return event


@pytest.mark.asyncio
async def test_cal_plan_uses_constitutional_prompt():
    """CAL plan events should use the constitutional classification prompt."""
    event = _make_cal_event()

    vllm_response = {
        "summary": "Professor terminated for expressing views in class.",
        "relevance": "relevant",
        "entities": [
            {"name": "UC Davis", "type": "organization"},
            {"name": "Prof. Smith", "type": "affected_individual"},
        ],
        "constitutional_basis": ["1A-free-speech"],
        "lead_type": "incident",
        "institution": "UC Davis",
        "jurisdiction": "CA",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response) as mock_vllm:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-cal-001")

    assert result["status"] == "enriched"
    # Verify constitutional fields stored in metadata
    assert event.metadata_["constitutional_basis"] == ["1A-free-speech"]
    assert event.metadata_["lead_type"] == "incident"
    assert event.metadata_["institution"] == "UC Davis"
    assert event.metadata_["jurisdiction"] == "CA"
    # Verify ATT&CK techniques NOT stored for CAL events
    assert "attack_techniques" not in event.metadata_

    # Verify the CAL system message was used
    call_kwargs = mock_vllm.call_args
    assert call_kwargs.kwargs["system_message"] is not None
    assert "constitutional rights" in call_kwargs.kwargs["system_message"]
    assert call_kwargs.kwargs["max_tokens"] == 800


@pytest.mark.asyncio
async def test_non_cal_plan_uses_original_prompt():
    """Non-CAL plan events should use the standard ATT&CK prompt."""
    event = MagicMock()
    event.id = "event-other"
    event.title = "Phishing campaign detected"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.plan_id = "some-other-plan"
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor phishing"},
        "keywords": ["phishing"],
    }
    event.metadata_ = {}

    vllm_response = {
        "summary": "Phishing campaign detected.",
        "relevance": "relevant",
        "entities": [],
        "attack_techniques": [{"id": "T1566", "name": "Phishing"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response) as mock_vllm:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-other")

    assert result["status"] == "enriched"
    # ATT&CK techniques stored
    assert event.metadata_["attack_techniques"] == [{"id": "T1566", "name": "Phishing"}]
    # Constitutional fields NOT stored
    assert "constitutional_basis" not in event.metadata_

    # Verify default system message (None means use default)
    call_kwargs = mock_vllm.call_args
    assert call_kwargs.kwargs["system_message"] is None
    assert call_kwargs.kwargs["max_tokens"] == 500


@pytest.mark.asyncio
async def test_cal_plan_filters_invalid_constitutional_basis():
    """Invalid constitutional basis labels should be filtered out."""
    event = _make_cal_event()

    vllm_response = {
        "summary": "Policy change at UCLA.",
        "relevance": "relevant",
        "entities": [],
        "constitutional_basis": ["1A-free-speech", "MADE-UP-LABEL", "14A-equal-protection"],
        "lead_type": "policy",
        "institution": "UCLA",
        "jurisdiction": "CA",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        await _enrich_event_async("event-cal-001")

    assert "MADE-UP-LABEL" not in event.metadata_["constitutional_basis"]
    assert event.metadata_["constitutional_basis"] == ["1A-free-speech", "14A-equal-protection"]


@pytest.mark.asyncio
async def test_cal_plan_removes_stale_attack_techniques():
    """CAL enrichment removes prior ATT&CK keys from metadata."""
    event = _make_cal_event()
    event.metadata_ = {"attack_techniques": [{"id": "T1566", "name": "Phishing"}], "other": 1}

    vllm_response = {
        "summary": "Speech code adopted at UT Austin.",
        "relevance": "relevant",
        "entities": [],
        "constitutional_basis": ["1A-free-speech"],
        "lead_type": "policy",
        "institution": "UT Austin",
        "jurisdiction": "TX",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-cal-001")

    assert result["status"] == "enriched"
    assert "attack_techniques" not in event.metadata_
    assert event.metadata_["constitutional_basis"] == ["1A-free-speech"]
    assert event.metadata_["other"] == 1  # unrelated keys preserved


@pytest.mark.asyncio
async def test_non_cal_plan_removes_stale_constitutional_keys():
    """Non-CAL enrichment removes prior CAL-specific keys from metadata."""
    event = MagicMock()
    event.id = "event-switched"
    event.title = "Phishing campaign"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.plan_id = "cyber-plan"
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor threats"},
        "keywords": ["phishing"],
    }
    event.metadata_ = {
        "constitutional_basis": ["1A-free-speech"],
        "lead_type": "incident",
        "institution": "UC Davis",
        "jurisdiction": "CA",
        "other": 2,
    }
    event.plan_version_id = "plan-uuid"

    vllm_response = {
        "summary": "Phishing campaign detected.",
        "relevance": "relevant",
        "entities": [],
        "attack_techniques": [{"id": "T1566", "name": "Phishing"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-switched")

    assert result["status"] == "enriched"
    assert "constitutional_basis" not in event.metadata_
    assert "lead_type" not in event.metadata_
    assert "institution" not in event.metadata_
    assert "jurisdiction" not in event.metadata_
    assert event.metadata_["attack_techniques"] == [{"id": "T1566", "name": "Phishing"}]
    assert event.metadata_["other"] == 2  # unrelated keys preserved


@pytest.mark.asyncio
async def test_cal_plan_handles_invalid_jurisdiction():
    """Invalid jurisdiction values should be set to None."""
    event = _make_cal_event()

    vllm_response = {
        "summary": "Event in New York.",
        "relevance": "tangential",
        "entities": [],
        "constitutional_basis": [],
        "lead_type": "incident",
        "institution": "NYU",
        "jurisdiction": "NY",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        await _enrich_event_async("event-cal-001")

    assert event.metadata_["jurisdiction"] is None


@pytest.mark.asyncio
async def test_cal_plan_multiple_constitutional_bases():
    """Events can have multiple constitutional bases."""
    event = _make_cal_event()

    vllm_response = {
        "summary": "Religious student group denied campus access.",
        "relevance": "relevant",
        "entities": [],
        "constitutional_basis": ["1A-religion", "1A-assembly", "14A-equal-protection"],
        "lead_type": "incident",
        "institution": "Texas A&M",
        "jurisdiction": "TX",
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_vllm", return_value=vllm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        await _enrich_event_async("event-cal-001")

    assert len(event.metadata_["constitutional_basis"]) == 3
    assert event.metadata_["lead_type"] == "incident"
    assert event.metadata_["institution"] == "Texas A&M"
    assert event.metadata_["jurisdiction"] == "TX"
