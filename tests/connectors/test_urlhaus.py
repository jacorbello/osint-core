"""Tests for the URLhaus feed connector."""

import hashlib

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.urlhaus import UrlhausConnector

SAMPLE_URLHAUS_RESPONSE = {
    "query_status": "ok",
    "urls": [
        {
            "id": "12345",
            "urlhaus_reference": "https://urlhaus.abuse.ch/url/12345/",
            "url": "http://malware.example.com/payload.exe",
            "url_status": "online",
            "host": "malware.example.com",
            "date_added": "2024-01-15 10:30:00 UTC",
            "threat": "malware_download",
            "blacklists": {
                "spamhaus_dbl": "not listed",
                "surbl": "not listed",
            },
            "reporter": "abuse_ch",
            "larted": "true",
            "tags": ["elf", "mirai"],
        },
        {
            "id": "12346",
            "urlhaus_reference": "https://urlhaus.abuse.ch/url/12346/",
            "url": "https://phishing.example.org/login.html",
            "url_status": "online",
            "host": "phishing.example.org",
            "date_added": "2024-01-15 11:00:00 UTC",
            "threat": "malware_download",
            "blacklists": {
                "spamhaus_dbl": "listed",
                "surbl": "listed",
            },
            "reporter": "security_researcher",
            "larted": "false",
            "tags": ["phishing"],
        },
    ],
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="urlhaus",
        type="urlhaus",
        url="https://urlhaus.abuse.ch/api/",
        weight=0.7,
    )


@pytest.fixture()
def connector(config: SourceConfig) -> UrlhausConnector:
    return UrlhausConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_urls(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_url(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["url"] == "http://malware.example.com/payload.exe"


@pytest.mark.asyncio
async def test_fetch_extracts_threat_type(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["threat"] == "malware_download"


@pytest.mark.asyncio
async def test_fetch_extracts_tags(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["tags"] == ["elf", "mirai"]


@pytest.mark.asyncio
async def test_fetch_extracts_reporter(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["reporter"] == "abuse_ch"


@pytest.mark.asyncio
async def test_fetch_creates_url_indicator(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    url_ind = next(i for i in items[0].indicators if i["type"] == "url")
    assert url_ind["value"] == "http://malware.example.com/payload.exe"


@pytest.mark.asyncio
async def test_fetch_creates_domain_indicator(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    domain_ind = next(i for i in items[0].indicators if i["type"] == "domain")
    assert domain_ind["value"] == "malware.example.com"


@pytest.mark.asyncio
async def test_dedupe_key_uses_url_hash(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    url_hash = hashlib.sha256(
        b"http://malware.example.com/payload.exe"
    ).hexdigest()[:16]
    assert connector.dedupe_key(items[0]) == f"urlhaus:{url_hash}"


@pytest.mark.asyncio
async def test_fetch_sets_title(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert "malware.example.com" in items[0].title


@pytest.mark.asyncio
async def test_fetch_sets_urlhaus_reference_as_item_url(
    connector: UrlhausConnector, respx_mock
):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_URLHAUS_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].url == "https://urlhaus.abuse.ch/url/12345/"


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"query_status": "ok", "urls": []})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_no_urls_key(connector: UrlhausConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"query_status": "no_results"})
    )
    items = await connector.fetch()
    assert items == []
