"""Tests for the Shodan API connector."""

import hashlib

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.shodan import ShodanConnector

SAMPLE_SEARCH_RESPONSE = {
    "matches": [
        {
            "ip_str": "203.0.113.50",
            "port": 443,
            "hostnames": ["example.com"],
            "domains": ["example.com"],
            "org": "Example Org",
            "isp": "Example ISP",
            "asn": "AS12345",
            "os": "Linux",
            "transport": "tcp",
            "product": "nginx",
            "version": "1.21.0",
            "vulns": ["CVE-2021-23017"],
            "location": {
                "country_code": "US",
                "city": "San Francisco",
                "latitude": 37.7749,
                "longitude": -122.4194,
            },
            "timestamp": "2026-03-03T12:00:00.000000",
        },
    ],
    "total": 1,
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="shodan",
        type="shodan_api",
        url="https://api.shodan.io/shodan/host/search",
        weight=0.9,
        extra={"api_key": "test-api-key", "query": "nginx"},
    )


@pytest.fixture()
def connector(config: SourceConfig) -> ShodanConnector:
    return ShodanConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_matches(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert items[0].title == "203.0.113.50:443 — nginx 1.21.0"
    assert items[0].url == "https://www.shodan.io/host/203.0.113.50"


@pytest.mark.asyncio
async def test_fetch_extracts_ip_indicator(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    ip_indicators = [i for i in items[0].indicators if i["type"] == "ip"]
    assert len(ip_indicators) == 1
    assert ip_indicators[0]["value"] == "203.0.113.50"


@pytest.mark.asyncio
async def test_fetch_extracts_cve_indicators(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    cve_indicators = [i for i in items[0].indicators if i["type"] == "cve"]
    assert len(cve_indicators) == 1
    assert cve_indicators[0]["value"] == "CVE-2021-23017"


@pytest.mark.asyncio
async def test_fetch_extracts_geolocation(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].latitude == 37.7749
    assert items[0].longitude == -122.4194
    assert items[0].country_code == "US"


@pytest.mark.asyncio
async def test_fetch_sets_source_category(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].source_category == "cyber"


@pytest.mark.asyncio
async def test_fetch_sends_api_key(connector: ShodanConnector, respx_mock):
    route = respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    await connector.fetch()
    request = route.calls[0].request
    assert "key=test-api-key" in str(request.url)
    assert "query=nginx" in str(request.url)


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json={"matches": [], "total": 0})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_dedupe_key_uses_ip_port_hash(connector: ShodanConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_SEARCH_RESPONSE)
    )
    items = await connector.fetch()
    raw = "203.0.113.50:443:2026-03-03T12:00:00.000000"
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    assert connector.dedupe_key(items[0]) == f"shodan:{expected_hash}"
