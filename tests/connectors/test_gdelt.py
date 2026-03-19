"""Tests for the GDELT DOC 2.0 API connector."""

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.gdelt import GdeltConnector

SAMPLE_GDELT_RESPONSE = {
    "articles": [
        {
            "url": "https://reuters.com/world/conflict-event-1",
            "title": "Military forces clash in border region",
            "seendate": "20260303T120000Z",
            "domain": "reuters.com",
            "language": "English",
            "sourcecountry": "United States",
            "tone": "-3.5",
        },
        {
            "url": "https://bbc.co.uk/news/world-event-2",
            "title": "Humanitarian crisis deepens in conflict zone",
            "seendate": "20260303T110000Z",
            "domain": "bbc.co.uk",
            "language": "English",
            "sourcecountry": "United Kingdom",
            "tone": "-5.2",
        },
    ]
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="gdelt",
        type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=0.7,
        extra={
            "query": "conflict",
            "mode": "ArtList",
            "format": "json",
            "maxrecords": "50",
            "timespan": "15min",
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> GdeltConnector:
    return GdeltConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_articles(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_title(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].title == "Military forces clash in border region"
    assert items[1].title == "Humanitarian crisis deepens in conflict zone"


@pytest.mark.asyncio
async def test_fetch_extracts_url(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].url == "https://reuters.com/world/conflict-event-1"
    assert items[1].url == "https://bbc.co.uk/news/world-event-2"


@pytest.mark.asyncio
async def test_fetch_extracts_occurred_at(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC)
    assert items[1].occurred_at == datetime(2026, 3, 3, 11, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fetch_sets_source_category(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].source_category == "geopolitical"
    assert items[1].source_category == "geopolitical"


@pytest.mark.asyncio
async def test_fetch_stores_raw_data(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["domain"] == "reuters.com"
    assert items[0].raw_data["language"] == "English"
    assert items[0].raw_data["sourcecountry"] == "United States"
    assert items[0].raw_data["tone"] == "-3.5"


@pytest.mark.asyncio
async def test_fetch_sends_query_params(connector: GdeltConnector, respx_mock):
    route = respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    await connector.fetch()
    request = route.calls.last.request
    assert "query=conflict" in str(request.url)
    assert "mode=ArtList" in str(request.url)
    assert "format=json" in str(request.url)
    assert "maxrecords=50" in str(request.url)
    assert "timespan=15min" in str(request.url)


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json={"articles": []})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_missing_articles_key(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json={})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_dedupe_key_uses_url_hash(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    url_hash = hashlib.sha256(
        b"https://reuters.com/world/conflict-event-1"
    ).hexdigest()[:16]
    key = connector.dedupe_key(items[0])
    assert key.startswith("gdelt:")
    assert key == f"gdelt:{url_hash}"


@pytest.mark.asyncio
async def test_dedupe_keys_differ(connector: GdeltConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) != connector.dedupe_key(items[1])


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_non_json_response(connector: GdeltConnector, respx_mock):
    """GDELT sometimes returns HTML or empty bodies instead of JSON."""
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, text="<html>Rate limited</html>")
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_empty_body(connector: GdeltConnector, respx_mock):
    """GDELT sometimes returns 200 with completely empty body."""
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, text="")
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_retries_on_429(connector: GdeltConnector, respx_mock):
    """429 responses should be retried with Retry-After delay."""
    respx_mock.get(connector.config.url).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json=SAMPLE_GDELT_RESPONSE),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    mock_sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_fetch_retries_on_503_with_default_delay(connector: GdeltConnector, respx_mock):
    """503 without Retry-After uses 10s default."""
    respx_mock.get(connector.config.url).mock(side_effect=[
        httpx.Response(503),
        httpx.Response(200, json=SAMPLE_GDELT_RESPONSE),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    mock_sleep.assert_awaited_once_with(10)


@pytest.mark.asyncio
async def test_fetch_returns_empty_after_max_retries(connector: GdeltConnector, respx_mock):
    """After 3 failed attempts, return empty list."""
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}),
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert items == []
    assert mock_sleep.await_count == 3


@pytest.mark.asyncio
async def test_fetch_no_retry_on_success(connector: GdeltConnector, respx_mock):
    """Successful first request does not retry."""
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_GDELT_RESPONSE),
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_caps_retry_after_at_60(connector: GdeltConnector, respx_mock):
    """Retry-After values above 60s are capped."""
    respx_mock.get(connector.config.url).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "300"}),
        httpx.Response(200, json=SAMPLE_GDELT_RESPONSE),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await connector.fetch()
    mock_sleep.assert_awaited_once_with(60)
