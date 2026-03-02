"""Tests for the intel brief generator service."""

import httpx
import pytest
import respx

from osint_core.services.brief_generator import BriefGenerator

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
def generator_no_ollama() -> BriefGenerator:
    """BriefGenerator with Ollama explicitly disabled."""
    return BriefGenerator(ollama_url="", ollama_model="", ollama_available=False)


@pytest.fixture()
def generator_with_ollama() -> BriefGenerator:
    """BriefGenerator pointing at a (mocked) Ollama endpoint."""
    return BriefGenerator(
        ollama_url="http://localhost:11434",
        ollama_model="llama3.1:8b",
        ollama_available=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_template_fallback_produces_markdown(generator_no_ollama: BriefGenerator):
    """Template-only generator produces valid markdown."""
    md = generator_no_ollama.generate_from_template(
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
async def test_ollama_generation(generator_with_ollama: BriefGenerator):
    """BriefGenerator calls Ollama API and returns the generated text."""
    ollama_response = {
        "model": "llama3.1:8b",
        "response": "## Threat Summary\n\nCritical CVE activity detected.",
        "done": True,
    }

    respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(200, json=ollama_response)
    )

    result = await generator_with_ollama.generate_from_ollama(
        query="Summarize recent CVE activity",
        context="CVE-2026-1234 was published with CVSS 9.8",
    )

    assert "Threat Summary" in result
    assert "Critical CVE activity detected" in result


@respx.mock
@pytest.mark.asyncio
async def test_ollama_fallback_on_error(generator_with_ollama: BriefGenerator):
    """When Ollama returns an error, generate() falls back to template."""
    respx.post("http://localhost:11434/api/generate").mock(
        return_value=httpx.Response(500, json={"error": "model not found"})
    )

    result = await generator_with_ollama.generate(
        query="Summarize threats",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    # Should still produce valid markdown via template fallback
    assert "# Intel Brief:" in result
    assert "CVE-2026-1234 Published" in result
    assert "192.168.1.100" in result


def test_template_includes_events_indicators_entities(generator_no_ollama: BriefGenerator):
    """Template output includes all provided events, indicators, and entities."""
    md = generator_no_ollama.generate_from_template(
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
