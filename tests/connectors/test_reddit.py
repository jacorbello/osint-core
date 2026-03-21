"""Tests for the Reddit connector."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.reddit import RedditConnector

SAMPLE_REDDIT_RESPONSE = {
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "abc123",
                    "title": "New APT campaign targeting critical infrastructure",
                    "selftext": "Researchers discovered a sophisticated campaign...",
                    "author": "threat_researcher",
                    "score": 452,
                    "url": "https://blog.example.com/apt-report",
                    "permalink": "/r/netsec/comments/abc123/new_apt_campaign/",
                    "subreddit": "netsec",
                    "created_utc": 1709467200.0,  # 2024-03-03T12:00:00Z
                    "num_comments": 87,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "def456",
                    "title": "Critical zero-day in popular library",
                    "selftext": "A zero-day vulnerability has been found...",
                    "author": "vuln_hunter",
                    "score": 1203,
                    "url": "https://www.reddit.com/r/netsec/comments/def456/critical_zeroday/",
                    "permalink": "/r/netsec/comments/def456/critical_zeroday/",
                    "subreddit": "netsec",
                    "created_utc": 1709463600.0,  # 2024-03-03T11:00:00Z
                    "num_comments": 234,
                },
            },
        ]
    }
}

SAMPLE_MULTI_SUBREDDIT_RESPONSE = {
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "ghi789",
                    "title": "Malware analysis of new ransomware variant",
                    "selftext": "Detailed analysis of the ransomware...",
                    "author": "malware_analyst",
                    "score": 88,
                    "url": "https://www.reddit.com/r/Malware/comments/ghi789/malware_analysis/",
                    "permalink": "/r/Malware/comments/ghi789/malware_analysis/",
                    "subreddit": "Malware",
                    "created_utc": 1709460000.0,
                    "num_comments": 15,
                },
            },
        ]
    }
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="reddit-netsec",
        type="reddit",
        url="https://www.reddit.com",
        weight=0.5,
        extra={
            "subreddits": ["netsec"],
            "sort": "hot",
            "limit": 25,
        },
    )


@pytest.fixture()
def multi_config() -> SourceConfig:
    return SourceConfig(
        id="reddit-multi",
        type="reddit",
        url="https://www.reddit.com",
        weight=0.5,
        extra={
            "subreddits": ["netsec", "Malware"],
            "sort": "new",
            "limit": 10,
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> RedditConnector:
    return RedditConnector(config)


@pytest.fixture()
def multi_connector(multi_config: SourceConfig) -> RedditConnector:
    return RedditConnector(multi_config)


# --- Basic fetch and parsing ---


@pytest.mark.asyncio
async def test_fetch_parses_posts(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_title(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].title == "New APT campaign targeting critical infrastructure"
    assert items[1].title == "Critical zero-day in popular library"


@pytest.mark.asyncio
async def test_fetch_extracts_url_as_permalink(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].url == "https://www.reddit.com/r/netsec/comments/abc123/new_apt_campaign/"
    assert items[1].url == "https://www.reddit.com/r/netsec/comments/def456/critical_zeroday/"


@pytest.mark.asyncio
async def test_fetch_extracts_selftext_as_summary(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].summary == "Researchers discovered a sophisticated campaign..."


@pytest.mark.asyncio
async def test_fetch_extracts_occurred_at(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2024, 3, 3, 12, 0, 0, tzinfo=UTC)
    assert items[1].occurred_at == datetime(2024, 3, 3, 11, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fetch_sets_source_category(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].source_category == "social_media"


@pytest.mark.asyncio
async def test_fetch_stores_raw_data(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["reddit_id"] == "abc123"
    assert items[0].raw_data["subreddit"] == "netsec"
    assert items[0].raw_data["author"] == "threat_researcher"
    # Volatile fields (score, num_comments) excluded from raw_data for stable dedupe
    assert "score" not in items[0].raw_data
    assert "num_comments" not in items[0].raw_data


# --- Multi-subreddit aggregation ---


@pytest.mark.asyncio
async def test_multi_subreddit_aggregation(multi_connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/new.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    respx_mock.get("https://www.reddit.com/r/Malware/new.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_MULTI_SUBREDDIT_RESPONSE)
    )
    items = await multi_connector.fetch()
    assert len(items) == 3
    subreddits = {item.raw_data["subreddit"] for item in items}
    assert subreddits == {"netsec", "Malware"}


# --- Keyword filtering ---


@pytest.mark.asyncio
async def test_keyword_filter_includes_matching(respx_mock):
    config = SourceConfig(
        id="reddit-filtered",
        type="reddit",
        url="https://www.reddit.com",
        weight=0.5,
        extra={
            "subreddits": ["netsec"],
            "sort": "hot",
            "keyword_filter": ["zero-day"],
        },
    )
    connector = RedditConnector(config)
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert "zero-day" in items[0].title.lower()


@pytest.mark.asyncio
async def test_keyword_filter_case_insensitive(respx_mock):
    config = SourceConfig(
        id="reddit-filtered",
        type="reddit",
        url="https://www.reddit.com",
        weight=0.5,
        extra={
            "subreddits": ["netsec"],
            "sort": "hot",
            "keyword_filter": ["APT"],
        },
    )
    connector = RedditConnector(config)
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert "apt" in items[0].title.lower()


# --- Deduplication ---


@pytest.mark.asyncio
async def test_dedupe_key_uses_reddit_id(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "reddit:abc123"
    assert connector.dedupe_key(items[1]) == "reddit:def456"


@pytest.mark.asyncio
async def test_dedupe_keys_differ(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) != connector.dedupe_key(items[1])


# --- Rate limiting ---


@pytest.mark.asyncio
async def test_fetch_retries_on_429(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    mock_sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_fetch_returns_empty_after_max_retries(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}),
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert items == []
    assert mock_sleep.await_count == 2  # skip sleep on last attempt


@pytest.mark.asyncio
async def test_fetch_caps_retry_after_at_60(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "300"}),
            httpx.Response(200, json=SAMPLE_REDDIT_RESPONSE),
        ]
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await connector.fetch()
    mock_sleep.assert_awaited_once_with(60)


# --- Edge cases ---


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json={"data": {"children": []}})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_no_subreddits_configured():
    config = SourceConfig(
        id="reddit-empty",
        type="reddit",
        url="https://www.reddit.com",
        weight=0.5,
        extra={},
    )
    connector = RedditConnector(config)
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_non_json_response(connector: RedditConnector, respx_mock):
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, text="<html>Error</html>")
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_skips_children_without_id(connector: RedditConnector, respx_mock):
    response = {
        "data": {
            "children": [
                {"kind": "t3", "data": {"id": "abc123", "title": "Valid post"}},
                {"kind": "t3", "data": {"title": "Missing ID post"}},
            ]
        }
    }
    respx_mock.get("https://www.reddit.com/r/netsec/hot.json").mock(
        return_value=httpx.Response(200, json=response)
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert items[0].title == "Valid post"
