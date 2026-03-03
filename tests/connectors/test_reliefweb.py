"""Tests for the ReliefWeb API v2 connector."""

from datetime import datetime, timezone

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.reliefweb import ReliefWebConnector

SAMPLE_RELIEFWEB_RESPONSE = {
    "count": 2,
    "data": [
        {
            "id": "4001234",
            "fields": {
                "title": "Flash Update: Earthquake in Region X",
                "body": "A magnitude 6.2 earthquake struck Region X early this morning, affecting an estimated 50,000 people.",
                "date": {"created": "2026-03-03T10:00:00+00:00"},
                "url": "https://reliefweb.int/report/country/flash-update-earthquake",
                "primary_country": {"iso3": "TUR", "name": "Türkiye"},
                "disaster_type": [{"name": "Earthquake"}],
                "source": [{"name": "OCHA"}],
                "status": "published",
            },
        },
        {
            "id": "4001235",
            "fields": {
                "title": "Situation Report: Refugee Crisis Update",
                "body": "UNHCR reports continued displacement in the border region with over 100,000 new arrivals.",
                "date": {"created": "2026-03-02T08:00:00+00:00"},
                "url": "https://reliefweb.int/report/country/sitrep-refugee-crisis",
                "primary_country": {"iso3": "SYR", "name": "Syrian Arab Republic"},
                "disaster_type": [{"name": "Complex Emergency"}],
                "source": [{"name": "UNHCR"}],
                "status": "published",
            },
        },
    ],
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="reliefweb",
        type="reliefweb_api",
        url="https://api.reliefweb.int/v1/reports",
        weight=0.8,
        extra={"appname": "osint-core"},
    )


@pytest.fixture()
def connector(config: SourceConfig) -> ReliefWebConnector:
    return ReliefWebConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_reports(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_title(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].title == "Flash Update: Earthquake in Region X"
    assert items[1].title == "Situation Report: Refugee Crisis Update"


@pytest.mark.asyncio
async def test_fetch_extracts_country_code(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].country_code == "TUR"
    assert items[1].country_code == "SYR"


@pytest.mark.asyncio
async def test_fetch_sets_source_category(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].source_category == "humanitarian"
    assert items[1].source_category == "humanitarian"


@pytest.mark.asyncio
async def test_fetch_extracts_occurred_at(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2026, 3, 3, 10, 0, 0, tzinfo=timezone.utc)
    assert items[1].occurred_at == datetime(2026, 3, 2, 8, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_truncates_body_for_summary(connector: ReliefWebConnector, respx_mock):
    long_body = "A" * 1000
    response = {
        "count": 1,
        "data": [
            {
                "id": "4001236",
                "fields": {
                    "title": "Long Report",
                    "body": long_body,
                    "date": {"created": "2026-03-03T10:00:00+00:00"},
                    "url": "https://reliefweb.int/report/country/long-report",
                    "primary_country": {"iso3": "TUR", "name": "Türkiye"},
                    "disaster_type": [{"name": "Earthquake"}],
                    "source": [{"name": "OCHA"}],
                    "status": "published",
                },
            }
        ],
    }
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=response)
    )
    items = await connector.fetch()
    assert len(items[0].summary) <= 500


@pytest.mark.asyncio
async def test_fetch_sends_appname(connector: ReliefWebConnector, respx_mock):
    route = respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    await connector.fetch()
    request = route.calls.last.request
    assert "appname=osint-core" in str(request.url)


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"count": 0, "data": []})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_dedupe_key_uses_report_id(connector: ReliefWebConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_RELIEFWEB_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "reliefweb:4001234"
    assert connector.dedupe_key(items[1]) == "reliefweb:4001235"
