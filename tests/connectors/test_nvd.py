"""Tests for the NVD API 2.0 feed connector."""

from datetime import datetime, timezone

import httpx
import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.connectors.nvd import NvdConnector

SAMPLE_NVD_RESPONSE = {
    "resultsPerPage": 2,
    "startIndex": 0,
    "totalResults": 2,
    "format": "NVD_CVE",
    "version": "2.0",
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2024-0001",
                "sourceIdentifier": "nvd@nist.gov",
                "published": "2024-01-10T12:00:00.000",
                "lastModified": "2024-01-11T08:00:00.000",
                "vulnStatus": "Analyzed",
                "descriptions": [
                    {"lang": "en", "value": "A critical buffer overflow in ExampleSoft."},
                    {"lang": "es", "value": "Un desbordamiento en ExampleSoft."},
                ],
                "metrics": {
                    "cvssMetricV31": [
                        {
                            "source": "nvd@nist.gov",
                            "type": "Primary",
                            "cvssData": {
                                "version": "3.1",
                                "baseScore": 9.8,
                                "baseSeverity": "CRITICAL",
                                "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                            },
                        }
                    ]
                },
                "references": [
                    {"url": "https://example.com/advisory/1", "source": "nvd@nist.gov"},
                    {"url": "https://example.com/patch/1", "source": "vendor"},
                ],
            }
        },
        {
            "cve": {
                "id": "CVE-2024-0002",
                "sourceIdentifier": "nvd@nist.gov",
                "published": "2024-01-12T10:00:00.000",
                "lastModified": "2024-01-12T15:00:00.000",
                "vulnStatus": "Awaiting Analysis",
                "descriptions": [
                    {"lang": "en", "value": "An XSS vulnerability in WebApp."},
                ],
                "metrics": {
                    "cvssMetricV31": [
                        {
                            "source": "nvd@nist.gov",
                            "type": "Primary",
                            "cvssData": {
                                "version": "3.1",
                                "baseScore": 6.1,
                                "baseSeverity": "MEDIUM",
                                "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",
                            },
                        }
                    ]
                },
                "references": [
                    {"url": "https://example.com/advisory/2", "source": "nvd@nist.gov"},
                ],
            }
        },
    ],
}

SAMPLE_NVD_PAGE2 = {
    "resultsPerPage": 1,
    "startIndex": 2,
    "totalResults": 3,
    "format": "NVD_CVE",
    "version": "2.0",
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2024-0003",
                "sourceIdentifier": "nvd@nist.gov",
                "published": "2024-01-13T10:00:00.000",
                "lastModified": "2024-01-13T15:00:00.000",
                "vulnStatus": "Analyzed",
                "descriptions": [
                    {"lang": "en", "value": "A SQL injection in DBTool."},
                ],
                "metrics": {},
                "references": [],
            }
        },
    ],
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="nvd",
        type="nvd",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0",
        weight=0.8,
    )


@pytest.fixture()
def connector(config: SourceConfig) -> NvdConnector:
    return NvdConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_cves(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_cve_id(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["id"] == "CVE-2024-0001"
    assert items[1].raw_data["id"] == "CVE-2024-0002"


@pytest.mark.asyncio
async def test_fetch_extracts_cvss_score(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].severity == "CRITICAL"
    assert items[1].severity == "MEDIUM"


@pytest.mark.asyncio
async def test_fetch_extracts_english_description(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert "buffer overflow" in items[0].summary.lower()
    assert "xss" in items[1].summary.lower()


@pytest.mark.asyncio
async def test_fetch_extracts_references(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    refs = items[0].raw_data["references"]
    assert len(refs) == 2


@pytest.mark.asyncio
async def test_dedupe_key_uses_cve_id(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "nvd:CVE-2024-0001"
    assert connector.dedupe_key(items[1]) == "nvd:CVE-2024-0002"


@pytest.mark.asyncio
async def test_fetch_creates_cve_indicators(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    cve_ind = next(i for i in items[0].indicators if i["type"] == "cve")
    assert cve_ind["value"] == "CVE-2024-0001"


@pytest.mark.asyncio
async def test_fetch_sets_occurred_at(connector: NvdConnector, respx_mock):
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_handles_pagination(connector: NvdConnector, respx_mock):
    page1 = SAMPLE_NVD_RESPONSE.copy()
    page1["totalResults"] = 3

    respx_mock.get(connector.config.url).mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=SAMPLE_NVD_PAGE2),
        ]
    )
    items = await connector.fetch()
    assert len(items) == 3
    assert items[2].raw_data["id"] == "CVE-2024-0003"


@pytest.mark.asyncio
async def test_fetch_no_cvss_score(connector: NvdConnector, respx_mock):
    """CVE without CVSS metrics should have None severity."""
    response = {
        "resultsPerPage": 1,
        "startIndex": 0,
        "totalResults": 1,
        "format": "NVD_CVE",
        "version": "2.0",
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2024-9999",
                    "sourceIdentifier": "nvd@nist.gov",
                    "published": "2024-01-15T10:00:00.000",
                    "lastModified": "2024-01-15T10:00:00.000",
                    "vulnStatus": "Received",
                    "descriptions": [{"lang": "en", "value": "No CVSS yet."}],
                    "metrics": {},
                    "references": [],
                }
            }
        ],
    }
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=response)
    )
    items = await connector.fetch()
    assert len(items) == 1
    assert items[0].severity is None


@pytest.mark.asyncio
async def test_fetch_empty_results(connector: NvdConnector, respx_mock):
    empty = {
        "resultsPerPage": 0,
        "startIndex": 0,
        "totalResults": 0,
        "format": "NVD_CVE",
        "version": "2.0",
        "vulnerabilities": [],
    }
    respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=empty)
    )
    items = await connector.fetch()
    assert items == []
