"""Tests for GDELT connector filtering enhancements."""
import httpx
import pytest
import respx

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.gdelt import GdeltConnector


@respx.mock
@pytest.mark.asyncio
async def test_geo_terms_appended_to_query():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={
            "query": "terrorism OR attack",
            "geo_terms": "Austin OR Texas",
            "mode": "ArtList",
            "maxrecords": "100",
        },
    )
    route = respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": []}))
    conn = GdeltConnector(cfg)
    await conn.fetch()
    called_params = dict(route.calls[0].request.url.params)
    assert "(terrorism OR attack) AND (Austin OR Texas)" in called_params.get("query", "")


@respx.mock
@pytest.mark.asyncio
async def test_preferred_languages_in_query():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={
            "query": "terrorism",
            "preferred_languages": ["English", "Spanish"],
            "mode": "ArtList",
            "maxrecords": "100",
        },
    )
    route = respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": []}))
    conn = GdeltConnector(cfg)
    await conn.fetch()
    called_params = dict(route.calls[0].request.url.params)
    q = called_params.get("query", "")
    assert "sourcelang:English" in q or "sourcelang:english" in q


@respx.mock
@pytest.mark.asyncio
async def test_extracts_country_code_from_sourcecountry():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={"query": "test", "mode": "ArtList", "maxrecords": "100"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": [
        {
            "url": "https://example.com/article",
            "title": "Test Article",
            "seendate": "20260316T120000Z",
            "sourcecountry": "United States",
            "language": "English",
            "domain": "example.com",
        },
    ]}))
    conn = GdeltConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].country_code == "USA"


@respx.mock
@pytest.mark.asyncio
async def test_max_per_domain_cap():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={"query": "test", "mode": "ArtList", "maxrecords": "100", "max_per_domain": 2},
    )
    articles = [
        {"url": f"https://spam.com/a{i}", "title": f"Spam {i}", "seendate": "20260316T120000Z",
         "sourcecountry": "United States", "language": "English", "domain": "spam.com"}
        for i in range(10)
    ]
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": articles}))
    conn = GdeltConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 2


@respx.mock
@pytest.mark.asyncio
async def test_lookback_hours_default():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={"query": "test", "mode": "ArtList", "maxrecords": "100"},
    )
    route = respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": []}))
    conn = GdeltConnector(cfg)
    await conn.fetch()
    called_params = dict(route.calls[0].request.url.params)
    assert called_params.get("timespan") == "240min"  # 4h default
