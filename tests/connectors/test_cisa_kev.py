"""Tests for the CISA KEV feed connector."""

from datetime import datetime, timezone

import httpx
import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.connectors.cisa_kev import CisaKevConnector

SAMPLE_KEV_RESPONSE = {
    "title": "CISA Known Exploited Vulnerabilities Catalog",
    "catalogVersion": "2024.01.01",
    "dateReleased": "2024-01-01T00:00:00.000Z",
    "count": 2,
    "vulnerabilities": [
        {
            "cveID": "CVE-2024-1234",
            "vendorProject": "Microsoft",
            "product": "Windows",
            "vulnerabilityName": "Microsoft Windows Privilege Escalation",
            "dateAdded": "2024-01-15",
            "shortDescription": "Microsoft Windows contains a privilege escalation vulnerability.",
            "requiredAction": "Apply updates per vendor instructions.",
            "dueDate": "2024-02-05",
            "knownRansomwareCampaignUse": "Known",
            "notes": "",
        },
        {
            "cveID": "CVE-2023-5678",
            "vendorProject": "Apache",
            "product": "HTTP Server",
            "vulnerabilityName": "Apache HTTP Server RCE",
            "dateAdded": "2024-01-10",
            "shortDescription": "Apache HTTP Server contains a remote code execution vulnerability.",
            "requiredAction": "Apply updates per vendor instructions.",
            "dueDate": "2024-01-31",
            "knownRansomwareCampaignUse": "Unknown",
            "notes": "Some additional notes.",
        },
    ],
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="cisa-kev",
        type="cisa_kev",
        url="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
        weight=0.9,
    )


@pytest.fixture()
def connector(config: SourceConfig) -> CisaKevConnector:
    return CisaKevConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_vulnerabilities(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_cve_id(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["cveID"] == "CVE-2024-1234"
    assert items[1].raw_data["cveID"] == "CVE-2023-5678"


@pytest.mark.asyncio
async def test_fetch_extracts_vendor_and_product(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["vendorProject"] == "Microsoft"
    assert items[0].raw_data["product"] == "Windows"


@pytest.mark.asyncio
async def test_fetch_extracts_description(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert "privilege escalation" in items[0].summary.lower()


@pytest.mark.asyncio
async def test_fetch_extracts_date_added(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2024, 1, 15, tzinfo=timezone.utc)
    assert items[1].occurred_at == datetime(2024, 1, 10, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_dedupe_key_uses_cve_id(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "cisa_kev:CVE-2024-1234"
    assert connector.dedupe_key(items[1]) == "cisa_kev:CVE-2023-5678"


@pytest.mark.asyncio
async def test_fetch_creates_indicators(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    indicators = items[0].indicators
    assert len(indicators) >= 1
    cve_indicator = next(i for i in indicators if i["type"] == "cve")
    assert cve_indicator["value"] == "CVE-2024-1234"


@pytest.mark.asyncio
async def test_fetch_sets_title(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert "CVE-2024-1234" in items[0].title
    assert "Microsoft" in items[0].title or "Windows" in items[0].title


@pytest.mark.asyncio
async def test_fetch_sets_url(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert "CVE-2024-1234" in items[0].url


@pytest.mark.asyncio
async def test_fetch_empty_catalog(connector: CisaKevConnector, respx_mock):
    empty_response = {
        "title": "CISA Known Exploited Vulnerabilities Catalog",
        "catalogVersion": "2024.01.01",
        "dateReleased": "2024-01-01T00:00:00.000Z",
        "count": 0,
        "vulnerabilities": [],
    }
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=empty_response)
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_ransomware_flag(connector: CisaKevConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_KEV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["knownRansomwareCampaignUse"] == "Known"
    assert items[1].raw_data["knownRansomwareCampaignUse"] == "Unknown"
