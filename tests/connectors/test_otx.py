"""Tests for AlienVault OTX connector."""
import pytest
import httpx
import respx
from osint_core.connectors.otx import OtxConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_fetches_pulses_and_extracts_iocs():
    cfg = SourceConfig(
        id="otx_feed", type="otx_api",
        url="https://otx.alienvault.com/api/v1/pulses/subscribed",
        weight=1.0,
        extra={"api_key": "test-key"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "results": [{
            "id": "pulse-1",
            "name": "Malware Campaign X",
            "description": "New malware targeting enterprise systems",
            "created": "2026-03-16T12:00:00",
            "indicators": [
                {"type": "IPv4", "indicator": "1.2.3.4"},
                {"type": "domain", "indicator": "evil.com"},
                {"type": "CVE", "indicator": "CVE-2026-1234"},
            ],
        }],
    }))
    conn = OtxConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].title == "Malware Campaign X"
    assert len(items[0].indicators) == 3
    assert items[0].indicators[0]["type"] == "IPv4"
