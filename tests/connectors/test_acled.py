"""Tests for ACLED conflict data connector."""
import httpx
import pytest
import respx

from osint_core.connectors import acled
from osint_core.connectors.acled import AcledConnector
from osint_core.connectors.base import SourceConfig

_ACLED_EVENT = {
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
}


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """Reset module-level token cache between tests."""
    acled._token_cache["access_token"] = ""
    acled._token_cache["expires_at"] = 0.0


@respx.mock
@pytest.mark.asyncio
async def test_parses_conflict_events():
    cfg = SourceConfig(
        id="acled_global", type="acled_api",
        url="https://acleddata.com/api/acled/read",
        weight=1.0,
        extra={"email": "test@test.com", "password": "secret"},
    )
    respx.post("https://acleddata.com/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok_test",
            "expires_in": 86400,
        }),
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "status": 200,
        "data": [_ACLED_EVENT],
    }))
    conn = AcledConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].country_code == "USA"
    assert items[0].latitude == pytest.approx(30.2672)
    assert items[0].fatalities == 0


@respx.mock
@pytest.mark.asyncio
async def test_token_is_cached():
    cfg = SourceConfig(
        id="acled_global", type="acled_api",
        url="https://acleddata.com/api/acled/read",
        weight=1.0,
        extra={"email": "test@test.com", "password": "secret"},
    )
    token_route = respx.post("https://acleddata.com/oauth/token").mock(
        return_value=httpx.Response(200, json={
            "access_token": "tok_cached",
            "expires_in": 86400,
        }),
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "status": 200,
        "data": [_ACLED_EVENT],
    }))
    conn = AcledConnector(cfg)
    await conn.fetch()
    await conn.fetch()
    # Token endpoint should only be called once due to caching.
    assert token_route.call_count == 1
