"""Tests for paste site monitor connector."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.pastebin import PasteSiteConnector


def _make_config(**extra: object) -> SourceConfig:
    return SourceConfig(
        id="paste_feed",
        type="pastebin",
        url="https://psbdmp.ws/api/v3/search",
        weight=1.0,
        extra={"keywords": ["password"], **extra},
    )


@respx.mock
@pytest.mark.asyncio
async def test_fetches_pastes_and_parses_fields():
    recent_ts = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    cfg = _make_config()
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc123",
                    "title": "Leaked credentials",
                    "content": "admin:password123 server 10.0.0.1",
                    "author": "anon_user",
                    "time": recent_ts,
                    "url": "https://pastebin.com/abc123",
                }
            ],
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    assert len(items) == 1
    assert items[0].title == "Leaked credentials"
    assert items[0].url == "https://pastebin.com/abc123"
    assert items[0].occurred_at is not None
    assert items[0].source_category == "cyber"
    assert "anon_user" in items[0].summary


@respx.mock
@pytest.mark.asyncio
async def test_indicator_extraction_from_paste_content():
    cfg = _make_config()
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "ioc1",
                    "content": (
                        "Found malware at 192.168.1.100 calling evil.example.com "
                        "hash d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592"
                    ),
                }
            ],
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    assert len(items) == 1
    indicator_types = {i["type"] for i in items[0].indicators}
    assert "ip" in indicator_types
    assert "domain" in indicator_types
    assert "hash" in indicator_types


@respx.mock
@pytest.mark.asyncio
async def test_deduplication_by_paste_id():
    cfg = _make_config(keywords=["password", "secret"])
    paste = {
        "id": "dup123",
        "content": "some leaked data",
        "title": "Duplicate paste",
    }
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(200, json=[paste])
    )
    respx.get("https://psbdmp.ws/api/v3/search/secret").mock(
        return_value=httpx.Response(200, json=[paste])
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    # The same paste ID should appear only once
    assert len(items) == 1


@respx.mock
@pytest.mark.asyncio
async def test_dedupe_key_is_stable():
    cfg = _make_config()
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200, json=[{"id": "stable1", "content": "data"}]
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    key1 = conn.dedupe_key(items[0])
    key2 = conn.dedupe_key(items[0])
    assert key1 == key2
    assert key1.startswith("pastebin:")


@respx.mock
@pytest.mark.asyncio
async def test_empty_keywords_returns_no_items():
    cfg = SourceConfig(
        id="paste_feed",
        type="pastebin",
        url="https://psbdmp.ws/api/v3/search",
        weight=1.0,
        extra={"keywords": []},
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()
    assert items == []


@respx.mock
@pytest.mark.asyncio
async def test_unix_timestamp_parsing():
    recent_unix = datetime.now(tz=UTC).timestamp() - 3600  # 1 hour ago
    cfg = _make_config()
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "ts1", "content": "data", "time": recent_unix}],
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].occurred_at is not None


@respx.mock
@pytest.mark.asyncio
async def test_max_items_limits_results():
    cfg = _make_config(max_items=2)
    pastes = [{"id": f"p{i}", "content": f"data {i}"} for i in range(5)]
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(200, json=pastes)
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 2


@respx.mock
@pytest.mark.asyncio
async def test_lookback_filters_old_pastes():
    """Pastes older than lookback_hours are excluded."""
    now = datetime.now(tz=UTC)
    old_ts = (now - timedelta(hours=50)).isoformat()
    recent_ts = (now - timedelta(hours=2)).isoformat()

    cfg = _make_config(lookback_hours=24)
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "old1", "content": "old data", "time": old_ts},
                {"id": "new1", "content": "new data", "time": recent_ts},
            ],
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    assert len(items) == 1
    assert items[0].raw_data["id"] == "new1"


@respx.mock
@pytest.mark.asyncio
async def test_lookback_keeps_pastes_without_timestamp():
    """Pastes with no timestamp are included regardless of lookback."""
    cfg = _make_config(lookback_hours=1)
    respx.get("https://psbdmp.ws/api/v3/search/password").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "nots1", "content": "no timestamp paste"},
            ],
        )
    )
    conn = PasteSiteConnector(cfg)
    items = await conn.fetch()

    assert len(items) == 1
    assert items[0].occurred_at is None
