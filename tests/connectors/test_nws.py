"""Tests for NWS weather alert connector."""
import httpx
import pytest
import respx

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.nws import NwsConnector


@respx.mock
@pytest.mark.asyncio
async def test_parses_weather_alerts():
    cfg = SourceConfig(
        id="nws_austin", type="nws_alerts",
        url="https://api.weather.gov/alerts/active",
        weight=1.0,
        extra={"zone": "TXC453"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "features": [{
            "id": "urn:oid:2.49.0.1.840.0.abc",
            "properties": {
                "headline": "Tornado Warning for Travis County",
                "description": "A tornado warning has been issued...",
                "severity": "Severe",
                "event": "Tornado Warning",
                "onset": "2026-03-16T14:00:00-05:00",
                "areaDesc": "Travis County, TX",
            },
        }],
    }))
    conn = NwsConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert "Tornado Warning" in items[0].title
    assert items[0].severity == "high"  # Severe -> high
