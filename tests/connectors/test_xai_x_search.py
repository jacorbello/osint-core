"""Tests for the xAI X Search connector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.xai_x_search import XaiXSearchConnector

# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------

SAMPLE_JSON_RESPONSE = {
    "id": "resp_001",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": json.dumps([
                        {
                            "tweet_url": "https://x.com/AustinPD/status/111111",
                            "author": "@AustinPD",
                            "text": "APD responding to reports of shots fired near downtown.",
                            "timestamp": "2026-03-26T10:30:00Z",
                            "category": "Active Shooter",
                        },
                        {
                            "tweet_url": "https://x.com/KVUE/status/222222",
                            "author": "@KVUE",
                            "text": "Breaking: police activity reported near Congress Ave.",
                            "timestamp": "2026-03-26T10:45:00Z",
                            "category": "Law Enforcement",
                        },
                    ]),
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://x.com/AustinPD/status/111111",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://x.com/KVUE/status/222222",
                        },
                    ],
                }
            ],
        }
    ],
    "usage": {"server_side_tool_usage_details": {"x_search_calls": 4}},
}

SAMPLE_ANNOTATION_ONLY_RESPONSE = {
    "id": "resp_002",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "I found some relevant posts about threats in Austin.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://x.com/AlertAustin/status/333333",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://x.com/TravisCoSO/status/444444",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://not-twitter.com/other/page",
                        },
                    ],
                }
            ],
        }
    ],
}

SAMPLE_EMPTY_RESPONSE = {
    "id": "resp_003",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "No relevant tweets found for the given searches.",
                    "annotations": [],
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="x_test",
        type="xai_x_search",
        url="",
        weight=0.4,
        extra={
            "api_key": "xai-test-key-123",
            "searches": [
                "(shooting OR gunfire) Austin lang:en",
                "reports of active shooter in Austin Texas",
            ],
            "mission": "Monitor threats in Austin, TX",
            "geo_terms": "Austin OR Travis County",
            "lookback_hours": 24,
            "max_results": 50,
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> XaiXSearchConnector:
    return XaiXSearchConnector(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_parses_json_response(
    connector: XaiXSearchConnector, respx_mock,
):
    """JSON array in Grok's text output is parsed into RawItems."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_JSON_RESPONSE),
    )
    items = await connector.fetch()

    assert len(items) == 2
    assert items[0].title == "@AustinPD: APD responding to reports of shots fired near downtown."
    assert items[0].url == "https://x.com/AustinPD/status/111111"
    assert items[0].source_category == "social_media"
    assert items[0].raw_data["author"] == "@AustinPD"
    assert items[0].occurred_at == datetime(2026, 3, 26, 10, 30, tzinfo=UTC)
    assert items[1].raw_data["category"] == "Law Enforcement"


@pytest.mark.asyncio
async def test_fetch_fallback_to_annotations(
    connector: XaiXSearchConnector, respx_mock,
):
    """When JSON parsing fails, tweets extracted from url_citation annotations."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_ANNOTATION_ONLY_RESPONSE),
    )
    items = await connector.fetch()

    # Should extract 2 x.com URLs, skip the non-twitter one
    assert len(items) == 2
    assert items[0].url == "https://x.com/AlertAustin/status/333333"
    assert items[0].raw_data["author"] == "@AlertAustin"
    assert items[1].raw_data["author"] == "@TravisCoSO"
    assert items[0].raw_data["category"] == "x_search"


@pytest.mark.asyncio
async def test_fetch_sends_date_params(
    connector: XaiXSearchConnector, respx_mock,
):
    """from_date and to_date computed from lookback_hours and sent in tool config."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    tool = body["tools"][0]
    assert tool["type"] == "x_search"
    assert "from_date" in tool
    assert "to_date" in tool
    # Dates should be YYYY-MM-DD format
    assert len(tool["from_date"]) == 10
    assert len(tool["to_date"]) == 10


@pytest.mark.asyncio
async def test_fetch_sends_tool_params(respx_mock):
    """excluded_x_handles, enable_image_understanding passed to tool object."""
    cfg = SourceConfig(
        id="x_test",
        type="xai_x_search",
        url="",
        weight=0.4,
        extra={
            "api_key": "xai-test-key-123",
            "searches": ["test query"],
            "excluded_x_handles": ["BotAccount", "SpamBot"],
            "enable_image_understanding": True,
        },
    )
    connector = XaiXSearchConnector(cfg)

    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    tool = body["tools"][0]
    assert tool["excluded_x_handles"] == ["BotAccount", "SpamBot"]
    assert tool["enable_image_understanding"] is True


@pytest.mark.asyncio
async def test_connector_keys_not_in_body(
    connector: XaiXSearchConnector, respx_mock,
):
    """Connector-only keys are not leaked as top-level API params or tool params."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    # These must NOT appear as top-level request body keys
    for key in ("searches", "mission", "geo_terms", "lookback_hours", "max_results"):
        assert key not in body, f"{key} leaked as top-level API param"
    # These must NOT appear as tool-level keys
    tool = body["tools"][0]
    for key in ("searches", "mission", "geo_terms", "lookback_hours", "max_results", "api_key"):
        assert key not in tool, f"{key} leaked as tool param"


@pytest.mark.asyncio
async def test_fetch_sends_auth_header(
    connector: XaiXSearchConnector, respx_mock,
):
    """API key sent as Bearer token in Authorization header."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    auth = route.calls[0].request.headers.get("authorization")
    assert auth == "Bearer xai-test-key-123"


def test_dedupe_key_uses_status_id(connector: XaiXSearchConnector):
    """Dedupe key extracts tweet status ID from URL."""
    from osint_core.connectors.base import RawItem

    item = RawItem(
        title="test",
        url="https://x.com/AustinPD/status/111111",
        raw_data={"tweet_url": "https://x.com/AustinPD/status/111111"},
    )
    assert connector.dedupe_key(item) == "xai:111111"


def test_dedupe_key_fallback_to_hash(connector: XaiXSearchConnector):
    """Dedupe falls back to URL hash when no status ID found."""
    from osint_core.connectors.base import RawItem

    item = RawItem(
        title="test",
        url="https://x.com/some/other/path",
        raw_data={"tweet_url": "https://x.com/some/other/path"},
    )
    key = connector.dedupe_key(item)
    assert key.startswith("xai:")
    assert len(key) > 10  # hash, not empty


@pytest.mark.asyncio
async def test_fetch_raises_on_missing_api_key(respx_mock):
    """ValueError raised when api_key is missing."""
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={"searches": ["test"]},
    )
    connector = XaiXSearchConnector(cfg)
    with pytest.raises(ValueError, match="api_key"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_fetch_raises_on_missing_searches(respx_mock):
    """ValueError raised when searches list is missing or empty."""
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={"api_key": "xai-test"},
    )
    connector = XaiXSearchConnector(cfg)
    with pytest.raises(ValueError, match="searches"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_fetch_empty_results(
    connector: XaiXSearchConnector, respx_mock,
):
    """Empty response returns empty list."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_max_results_caps_output(respx_mock):
    """max_results limits the number of RawItems returned."""
    tweets = [
        {
            "tweet_url": f"https://x.com/user/status/{i}",
            "author": f"@user{i}",
            "text": f"Tweet {i}",
            "timestamp": "2026-03-26T10:00:00Z",
            "category": "Test",
        }
        for i in range(10)
    ]
    response = {
        "id": "resp_big",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": json.dumps(tweets),
                "annotations": [],
            }],
        }],
    }
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={
            "api_key": "xai-test",
            "searches": ["test"],
            "max_results": 5,
        },
    )
    connector = XaiXSearchConnector(cfg)
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=response),
    )
    items = await connector.fetch()
    assert len(items) == 5


@pytest.mark.asyncio
async def test_fetch_retries_on_429(
    connector: XaiXSearchConnector, respx_mock,
):
    """429 is retried with backoff, then succeeds."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json=SAMPLE_JSON_RESPONSE),
        ],
    )
    with patch("osint_core.connectors.xai_x_search.asyncio.sleep", new_callable=AsyncMock):
        items = await connector.fetch()
    assert len(items) == 2
    assert route.call_count == 2  # confirm retry occurred


@pytest.mark.asyncio
async def test_fetch_429_exhaustion_returns_empty(
    connector: XaiXSearchConnector, respx_mock,
):
    """All 3 retry attempts return 429 — graceful degradation to empty list."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}),
    )
    with patch("osint_core.connectors.xai_x_search.asyncio.sleep", new_callable=AsyncMock):
        items = await connector.fetch()
    assert items == []
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_annotation_fallback_handles_redirect_urls(
    connector: XaiXSearchConnector, respx_mock,
):
    """x.com/i/status/ redirect URLs show (unknown) author, not @i."""
    response = {
        "id": "resp_redirect",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": "Found some relevant posts about threats.",
                "annotations": [
                    {"type": "url_citation", "url": "https://x.com/i/status/555555"},
                ],
            }],
        }],
    }
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=response),
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert items[0].raw_data["author"] == "(unknown)"
    assert "@i" not in items[0].title


@pytest.mark.asyncio
async def test_annotation_fallback_extracts_context(
    connector: XaiXSearchConnector, respx_mock,
):
    """Citation context is extracted from surrounding text when URL appears in response."""
    response = {
        "id": "resp_context",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": (
                    "Reports of gunfire near downtown Austin"
                    " https://x.com/AustinPD/status/666666"
                    " officers responding"
                ),
                "annotations": [
                    {"type": "url_citation", "url": "https://x.com/AustinPD/status/666666"},
                ],
            }],
        }],
    }
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=response),
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert "gunfire" in items[0].summary.lower()
    assert items[0].raw_data["author"] == "@AustinPD"


@pytest.mark.asyncio
async def test_annotation_fallback_uses_response_text_when_no_context(
    connector: XaiXSearchConnector, respx_mock,
):
    """When citation URL not found in text, summary falls back to response text."""
    response = {
        "id": "resp_no_context",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": "Multiple threats detected in the Austin area today.",
                "annotations": [
                    {"type": "url_citation", "url": "https://x.com/someone/status/777777"},
                ],
            }],
        }],
    }
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=response),
    )
    items = await connector.fetch()
    assert len(items) == 1
    # Should have the response text as summary, not empty string
    assert "threats detected" in items[0].summary.lower()
    assert items[0].raw_data["text"] != ""
