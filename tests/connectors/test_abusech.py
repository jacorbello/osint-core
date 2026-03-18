"""Tests for Abuse.ch connectors."""
import httpx
import pytest
import respx

from osint_core.connectors.abusech import FeodoTrackerConnector, MalwareBazaarConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_malwarebazaar_parses_samples():
    cfg = SourceConfig(
        id="mb_recent", type="abusech_malwarebazaar",
        url="https://mb-api.abuse.ch/api/v1/",
        weight=1.0, extra={},
    )
    respx.post(cfg.url).mock(return_value=httpx.Response(200, json={
        "query_status": "ok",
        "data": [{
            "sha256_hash": "abc123def456",
            "file_type": "exe",
            "signature": "AgentTesla",
            "first_seen": "2026-03-16 12:00:00",
            "tags": ["stealer"],
        }],
    }))
    conn = MalwareBazaarConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert "AgentTesla" in items[0].title
    assert items[0].indicators[0]["type"] == "sha256"


@respx.mock
@pytest.mark.asyncio
async def test_feodotracker_parses_c2_ips():
    cfg = SourceConfig(
        id="feodo_recent", type="abusech_feodotracker",
        url="https://feodotracker.abuse.ch/downloads/ipblocklist_recent.json",
        weight=1.0, extra={},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json=[
        {
            "ip_address": "1.2.3.4",
            "port": 443,
            "status": "online",
            "malware": "Dridex",
            "first_seen": "2026-03-16",
            "country": "US",
        },
    ]))
    conn = FeodoTrackerConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].indicators[0]["value"] == "1.2.3.4"
    assert items[0].country_code == "USA"
