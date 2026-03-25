"""Tests for the generic RSS/Atom feed connector."""

import hashlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.rss import RssConnector

SAMPLE_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Security News</title>
    <link>https://security.example.com</link>
    <description>Latest security news</description>
    <item>
      <title>Critical vulnerability found in OpenSSL</title>
      <link>https://security.example.com/openssl-vuln</link>
      <description>A critical vulnerability has been discovered in OpenSSL.</description>
      <pubDate>Mon, 15 Jan 2024 10:00:00 GMT</pubDate>
      <guid>https://security.example.com/openssl-vuln</guid>
    </item>
    <item>
      <title>New ransomware campaign targets healthcare</title>
      <link>https://security.example.com/ransomware-healthcare</link>
      <description>Healthcare orgs targeted by new ransomware variant.</description>
      <pubDate>Sun, 14 Jan 2024 08:00:00 GMT</pubDate>
      <guid>https://security.example.com/ransomware-healthcare</guid>
    </item>
  </channel>
</rss>"""

SAMPLE_ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Threat Intel Blog</title>
  <link href="https://blog.example.com"/>
  <updated>2024-01-15T12:00:00Z</updated>
  <entry>
    <title>APT Group Analysis</title>
    <link href="https://blog.example.com/apt-analysis"/>
    <summary>Detailed analysis of APT group activities.</summary>
    <updated>2024-01-15T12:00:00Z</updated>
    <id>urn:uuid:12345</id>
  </entry>
</feed>"""


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="security-rss",
        type="rss",
        url="https://security.example.com/rss.xml",
        weight=0.5,
    )


@pytest.fixture()
def connector(config: SourceConfig) -> RssConnector:
    return RssConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_rss_entries(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_title(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert items[0].title == "Critical vulnerability found in OpenSSL"
    assert items[1].title == "New ransomware campaign targets healthcare"


@pytest.mark.asyncio
async def test_fetch_extracts_link(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert items[0].url == "https://security.example.com/openssl-vuln"
    assert items[1].url == "https://security.example.com/ransomware-healthcare"


@pytest.mark.asyncio
async def test_fetch_extracts_summary(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert "critical vulnerability" in items[0].summary.lower()


@pytest.mark.asyncio
async def test_fetch_extracts_published_date(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert items[0].occurred_at is not None
    assert items[0].occurred_at.year == 2024
    assert items[0].occurred_at.month == 1
    assert items[0].occurred_at.day == 15


@pytest.mark.asyncio
async def test_dedupe_key_uses_feed_id_and_link_hash(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    link_hash = hashlib.sha256(
        b"https://security.example.com/openssl-vuln"
    ).hexdigest()[:16]
    assert connector.dedupe_key(items[0]) == f"rss:security-rss:{link_hash}"


@pytest.mark.asyncio
async def test_fetch_parses_atom_feed(respx_mock):
    config = SourceConfig(
        id="threat-blog",
        type="rss",
        url="https://blog.example.com/atom.xml",
        weight=0.5,
    )
    connector = RssConnector(config)
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_ATOM_FEED, headers={"content-type": "application/atom+xml"}
        )
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert items[0].title == "APT Group Analysis"
    assert items[0].url == "https://blog.example.com/apt-analysis"


@pytest.mark.asyncio
async def test_fetch_empty_feed(connector: RssConnector, respx_mock):
    empty_feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
    <link>https://example.com</link>
    <description>No items</description>
  </channel>
</rss>"""
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=empty_feed, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_stores_raw_entry_data(connector: RssConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert "title" in items[0].raw_data
    assert "link" in items[0].raw_data


@pytest.mark.asyncio
async def test_dedupe_key_different_for_different_entries(
    connector: RssConnector, respx_mock
):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(
            200, content=SAMPLE_RSS_FEED, headers={"content-type": "application/rss+xml"}
        )
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) != connector.dedupe_key(items[1])


# --- Retry logic tests ---


@pytest.mark.asyncio
async def test_fetch_retries_on_429(connector: RssConnector, respx_mock):
    """RSS connector retries on 429 and succeeds on subsequent attempt."""
    route = respx_mock.get(connector.config.url)
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, content=SAMPLE_RSS_FEED),
    ]
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    assert route.call_count == 2
    mock_sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_fetch_retries_on_5xx(connector: RssConnector, respx_mock):
    """RSS connector retries on 503 and succeeds on subsequent attempt."""
    route = respx_mock.get(connector.config.url)
    route.side_effect = [
        httpx.Response(503),
        httpx.Response(200, content=SAMPLE_RSS_FEED),
    ]
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert len(items) == 2
    assert route.call_count == 2
    mock_sleep.assert_awaited_once_with(1)  # 2^0 = 1s exponential backoff


@pytest.mark.asyncio
async def test_fetch_returns_empty_after_max_retries(connector: RssConnector, respx_mock):
    """RSS connector returns empty list after exhausting retries."""
    route = respx_mock.get(connector.config.url)
    route.side_effect = [httpx.Response(503)] * 3
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert items == []
    assert route.call_count == 3
    assert mock_sleep.await_count == 2  # skip sleep on last attempt


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_transport_error(connector: RssConnector, respx_mock):
    """RSS connector returns empty list after transport errors exhaust retries."""
    route = respx_mock.get(connector.config.url)
    route.side_effect = [httpx.ConnectError("connection refused")] * 3
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        items = await connector.fetch()
    assert items == []
    assert route.call_count == 3
    assert mock_sleep.await_count == 2  # skip sleep on last attempt


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_non_retryable_error(connector: RssConnector, respx_mock):
    """RSS connector returns empty immediately on 404 (non-retryable)."""
    route = respx_mock.get(connector.config.url)
    route.side_effect = [httpx.Response(404)]
    items = await connector.fetch()
    assert items == []
    assert route.call_count == 1
