"""Tests for ACLED conflict data connector."""
import pytest
import httpx
import respx
from osint_core.connectors.acled import AcledConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_parses_conflict_events():
    cfg = SourceConfig(
        id="acled_global", type="acled_api",
        url="https://api.acleddata.com/acled/read",
        weight=1.0,
        extra={"api_key": "test", "email": "test@test.com"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "status": 200,
        "data": [{
            "event_id_cnty": "USA12345",
            "event_date": "2026-03-16",
            "event_type": "Protests",
            "sub_event_type": "Peaceful protest",
            "actor1": "Protesters",
            "country": "United States",
            "iso3": "USA",
            "latitude": "30.2672",
            "longitude": "-97.7431",
            "fatalities": "0",
            "notes": "Peaceful march in downtown Austin",
        }],
    }))
    conn = AcledConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].country_code == "USA"
    assert items[0].latitude == pytest.approx(30.2672)
    assert items[0].fatalities == 0
