"""Tests for the intel brief generator service."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.services.brief_generator import (
    BriefContext,
    BriefGenerator,
    fetch_brief_context,
    serialize_events_for_context,
)

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
    """BriefGenerator with LLM explicitly disabled."""
    return BriefGenerator(llm_available=False)


@pytest.fixture()
def generator_with_vllm() -> BriefGenerator:
    """BriefGenerator with LLM enabled (mocked via llm_chat_completion)."""
    return BriefGenerator(llm_available=True)


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


@pytest.mark.asyncio
async def test_vllm_generation(generator_with_vllm: BriefGenerator):
    """BriefGenerator calls llm_chat_completion and returns the generated text."""
    with patch(
        "osint_core.services.brief_generator.llm_chat_completion",
        return_value="## Threat Summary\n\nCritical CVE activity detected.",
    ):
        result = await generator_with_vllm.generate_from_vllm(
            query="Summarize recent CVE activity",
            context="CVE-2026-1234 was published with CVSS 9.8",
        )

    assert "Threat Summary" in result
    assert "Critical CVE activity detected" in result


@pytest.mark.asyncio
async def test_vllm_fallback_on_error(generator_with_vllm: BriefGenerator):
    """When LLM raises an error, generate() falls back to template."""
    with patch(
        "osint_core.services.brief_generator.llm_chat_completion",
        side_effect=RuntimeError("model not found"),
    ):
        result, generated_by = await generator_with_vllm.generate(
            query="Summarize threats",
            events=SAMPLE_EVENTS,
            indicators=SAMPLE_INDICATORS,
            entities=SAMPLE_ENTITIES,
        )

    # Should still produce valid markdown via template fallback
    assert "# Intel Brief:" in result
    assert "CVE-2026-1234 Published" in result
    assert "192.168.1.100" in result
    assert generated_by == "template"


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
    def __init__(
        self, id, title, severity, score, source_id, occurred_at,
        entities=None, indicators=None,
    ):
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


@pytest.mark.asyncio
async def test_vllm_receives_event_context(generator_with_vllm: BriefGenerator):
    """When events are provided, the LLM prompt includes their data."""
    captured_messages: list = []

    async def _fake_llm(**kwargs):
        captured_messages.append(kwargs["messages"])
        return "## Brief\n\nAnalysis complete."

    with patch(
        "osint_core.services.brief_generator.llm_chat_completion",
        side_effect=_fake_llm,
    ):
        content_md, generated_by = await generator_with_vllm.generate(
            query="Austin terrorism",
            events=SAMPLE_EVENTS,
            indicators=SAMPLE_INDICATORS,
            entities=SAMPLE_ENTITIES,
        )

    # The prompt sent to LLM should include actual event data
    sent_prompt = captured_messages[0][0]["content"]
    assert "CVE-2026-1234 Published" in sent_prompt
    assert "192.168.1.100" in sent_prompt
    assert "APT-29" in sent_prompt
    assert generated_by == "llm"


# ---------------------------------------------------------------------------
# Empty context / hallucination prevention tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_empty_events_skips_vllm(generator_with_vllm: BriefGenerator):
    """When events list is empty, generate() must NOT call the LLM."""
    mock_llm = MagicMock()

    with patch(
        "osint_core.services.brief_generator.llm_chat_completion",
        mock_llm,
    ):
        result, generated_by = await generator_with_vllm.generate(
            query="What are the current terror threats in Austin, Texas?",
            events=[],
            indicators=[],
            entities=[],
        )

    mock_llm.assert_not_called()
    assert "# No Matching Events" in result
    assert "Austin, Texas" in result
    assert generated_by == "none"


@pytest.mark.asyncio
async def test_generate_empty_events_returns_template_markdown(generator_no_vllm: BriefGenerator):
    """Empty events with vLLM disabled also returns the no-match template."""
    result, generated_by = await generator_no_vllm.generate(
        query="Terror threats Austin",
        events=[],
        indicators=[],
        entities=[],
    )

    assert "# No Matching Events" in result
    assert "Terror threats Austin" in result
    assert "**Query:**" in result
    assert "**Generated at:**" in result
    assert generated_by == "none"


@pytest.mark.asyncio
async def test_generate_non_empty_events_still_calls_vllm_path(generator_no_vllm: BriefGenerator):
    """Non-empty events still follow the normal generation path (template here since no vLLM)."""
    result, generated_by = await generator_no_vllm.generate(
        query="Weekly brief",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    # Should use the template path (no vLLM available) and include event data
    assert "# No Matching Events" not in result
    assert "CVE-2026-1234 Published" in result
    assert generated_by == "template"


# ---------------------------------------------------------------------------
# fetch_brief_context uses websearch_to_tsquery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_brief_context_uses_websearch_to_tsquery():
    """fetch_brief_context must use websearch_to_tsquery, not plainto_tsquery."""
    db = MagicMock(spec=AsyncSession)

    # Capture the statement passed to db.execute
    captured_stmts: list = []

    async def fake_execute(stmt, *args, **kwargs):
        captured_stmts.append(stmt)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    db.execute = fake_execute

    with patch("osint_core.services.brief_generator.func") as mock_func:
        mock_func.websearch_to_tsquery = MagicMock(return_value="<tsquery>")
        mock_func.plainto_tsquery = MagicMock(return_value="<plainto_tsquery_should_not_be_called>")

        await fetch_brief_context(db, "terror threats Austin Texas")

        mock_func.websearch_to_tsquery.assert_called_once_with(
            "english", "terror threats Austin Texas",
        )
        mock_func.plainto_tsquery.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_brief_context_returns_empty_brief_context_on_no_events():
    """fetch_brief_context returns an all-empty BriefContext when no events match."""
    db = MagicMock(spec=AsyncSession)

    async def fake_execute(stmt, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    db.execute = fake_execute

    ctx = await fetch_brief_context(db, "nonexistent query xyz")

    assert isinstance(ctx, BriefContext)
    assert ctx.events == []
    assert ctx.entities == []
    assert ctx.indicators == []
    assert ctx.event_ids == []
    assert ctx.entity_ids == []
    assert ctx.indicator_ids == []
