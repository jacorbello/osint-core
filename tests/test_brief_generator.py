"""Tests for the intel brief generator service."""

import uuid

import httpx
import pytest
import respx

from osint_core.services.brief_generator import BriefGenerator, serialize_events_for_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_EVENTS = [
    {
        "title": "CVE-2026-1234 Published",
        "severity": "high",
        "score": 7.5,
        "source_id": "nvd_feeds_recent",
        "occurred_at": "2026-03-01T10:00:00Z",
    },
    {
        "title": "Suspicious DNS Queries",
        "severity": "medium",
        "score": 3.2,
        "source_id": "abuse_ch_urlhaus",
        "occurred_at": "2026-03-01T12:00:00Z",
    },
]

SAMPLE_INDICATORS = [
    {"value": "192.168.1.100", "type": "ipv4"},
    {"value": "evil.example.com", "type": "domain"},
]

SAMPLE_ENTITIES = [
    {"name": "APT-29", "entity_type": "threat-actor"},
    {"name": "Acme Corp", "entity_type": "organization"},
]


@pytest.fixture()
def generator_no_vllm() -> BriefGenerator:
    """BriefGenerator with vLLM explicitly disabled."""
    return BriefGenerator(vllm_url="", llm_model="", llm_available=False)


@pytest.fixture()
def generator_with_vllm() -> BriefGenerator:
    """BriefGenerator pointing at a (mocked) vLLM endpoint."""
    return BriefGenerator(
        vllm_url="http://localhost:8000",
        llm_model="meta-llama/Llama-3.2-3B-Instruct",
        llm_available=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_template_fallback_produces_markdown(generator_no_vllm: BriefGenerator):
    """Template-only generator produces valid markdown."""
    md = generator_no_vllm.generate_from_template(
        title="Weekly Threat Report",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    assert isinstance(md, str)
    assert "# Intel Brief: Weekly Threat Report" in md
    assert "template" in md.lower() or "Template" in md  # generated_by
    assert "CVE-2026-1234 Published" in md
    assert "192.168.1.100" in md
    assert "APT-29" in md


@respx.mock
@pytest.mark.asyncio
async def test_vllm_generation(generator_with_vllm: BriefGenerator):
    """BriefGenerator calls vLLM API and returns the generated text."""
    vllm_response = {
        "choices": [
            {
                "message": {
                    "content": "## Threat Summary\n\nCritical CVE activity detected."
                }
            }
        ]
    }

    respx.post("http://localhost:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=vllm_response)
    )

    result = await generator_with_vllm.generate_from_vllm(
        query="Summarize recent CVE activity",
        context="CVE-2026-1234 was published with CVSS 9.8",
    )

    assert "Threat Summary" in result
    assert "Critical CVE activity detected" in result


@respx.mock
@pytest.mark.asyncio
async def test_vllm_fallback_on_error(generator_with_vllm: BriefGenerator):
    """When vLLM returns an error, generate() falls back to template."""
    respx.post("http://localhost:8000/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "model not found"})
    )

    result = await generator_with_vllm.generate(
        query="Summarize threats",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    # Should still produce valid markdown via template fallback
    assert "# Intel Brief:" in result
    assert "CVE-2026-1234 Published" in result
    assert "192.168.1.100" in result


def test_template_includes_events_indicators_entities(generator_no_vllm: BriefGenerator):
    """Template output includes all provided events, indicators, and entities."""
    md = generator_no_vllm.generate_from_template(
        title="Full Data Brief",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    # All events present
    assert "CVE-2026-1234 Published" in md
    assert "Suspicious DNS Queries" in md
    assert "high" in md
    assert "7.5" in md or "7.5" in md

    # All indicators present
    assert "192.168.1.100" in md
    assert "evil.example.com" in md
    assert "ipv4" in md
    assert "domain" in md

    # All entities present
    assert "APT-29" in md
    assert "threat-actor" in md
    assert "Acme Corp" in md
    assert "organization" in md

    # Section headers present
    assert "## Key Events" in md
    assert "## Indicators of Compromise" in md
    assert "## Entities" in md
    assert "## Summary" in md


# ---------------------------------------------------------------------------
# serialize_events_for_context tests
# ---------------------------------------------------------------------------


class _FakeEntity:
    def __init__(self, id, name, entity_type):
        self.id = id
        self.name = name
        self.entity_type = entity_type


class _FakeIndicator:
    def __init__(self, id, value, indicator_type):
        self.id = id
        self.value = value
        self.indicator_type = indicator_type


class _FakeEvent:
    def __init__(self, id, title, severity, score, source_id, occurred_at, entities=None, indicators=None):
        self.id = id
        self.title = title
        self.severity = severity
        self.score = score
        self.source_id = source_id
        self.occurred_at = occurred_at
        self.entities = entities or []
        self.indicators = indicators or []


def test_serialize_events_for_context_extracts_event_fields():
    """serialize_events_for_context returns dicts with correct keys from ORM objects."""
    evt_id = uuid.uuid4()
    ent_id = uuid.uuid4()
    ind_id = uuid.uuid4()

    entity = _FakeEntity(id=ent_id, name="APT-29", entity_type="threat-actor")
    indicator = _FakeIndicator(id=ind_id, value="10.0.0.1", indicator_type="ipv4")
    event = _FakeEvent(
        id=evt_id,
        title="Border clash",
        severity="high",
        score=7.5,
        source_id="gdelt",
        occurred_at="2026-03-01T10:00:00Z",
        entities=[entity],
        indicators=[indicator],
    )

    events, entities, indicators, event_ids, entity_ids, indicator_ids = (
        serialize_events_for_context([event])
    )

    assert len(events) == 1
    assert events[0]["title"] == "Border clash"
    assert events[0]["severity"] == "high"
    assert events[0]["score"] == 7.5

    assert len(entities) == 1
    assert entities[0]["name"] == "APT-29"
    assert entities[0]["entity_type"] == "threat-actor"

    assert len(indicators) == 1
    assert indicators[0]["value"] == "10.0.0.1"
    assert indicators[0]["type"] == "ipv4"

    assert event_ids == [evt_id]
    assert entity_ids == [ent_id]
    assert indicator_ids == [ind_id]


def test_serialize_events_for_context_deduplicates_entities():
    """Entities/indicators shared across events should not be duplicated."""
    shared_ent_id = uuid.uuid4()
    entity = _FakeEntity(id=shared_ent_id, name="Shared", entity_type="org")

    evt1 = _FakeEvent(id=uuid.uuid4(), title="E1", severity="low", score=1.0,
                       source_id="a", occurred_at=None, entities=[entity])
    evt2 = _FakeEvent(id=uuid.uuid4(), title="E2", severity="low", score=2.0,
                       source_id="b", occurred_at=None, entities=[entity])

    events, entities, indicators, event_ids, entity_ids, indicator_ids = (
        serialize_events_for_context([evt1, evt2])
    )

    assert len(events) == 2
    assert len(entities) == 1  # deduplicated
    assert entity_ids == [shared_ent_id]


@respx.mock
@pytest.mark.asyncio
async def test_vllm_receives_event_context(generator_with_vllm: BriefGenerator):
    """When events are provided, the LLM prompt includes their data."""
    vllm_response = {
        "choices": [{"message": {"content": "## Brief\n\nAnalysis complete."}}]
    }

    route = respx.post("http://localhost:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=vllm_response)
    )

    await generator_with_vllm.generate(
        query="Austin terrorism",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    sent_body = route.calls.last.request.content.decode()
    # The prompt sent to vLLM should include actual event data
    assert "CVE-2026-1234 Published" in sent_body
    assert "192.168.1.100" in sent_body
    assert "APT-29" in sent_body
