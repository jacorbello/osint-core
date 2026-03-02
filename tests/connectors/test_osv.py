"""Tests for the OSV API feed connector."""

import httpx
import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.connectors.osv import OsvConnector

SAMPLE_OSV_RESPONSE = {
    "vulns": [
        {
            "id": "GHSA-xxxx-yyyy-zzzz",
            "summary": "Remote code execution in example-package",
            "details": "A detailed description of the vulnerability.",
            "aliases": ["CVE-2024-1111"],
            "modified": "2024-01-15T10:00:00Z",
            "published": "2024-01-10T08:00:00Z",
            "database_specific": {},
            "references": [
                {"type": "ADVISORY", "url": "https://example.com/advisory/1"},
                {"type": "FIX", "url": "https://example.com/fix/1"},
            ],
            "affected": [
                {
                    "package": {
                        "ecosystem": "PyPI",
                        "name": "example-package",
                    },
                    "ranges": [
                        {
                            "type": "ECOSYSTEM",
                            "events": [
                                {"introduced": "0"},
                                {"fixed": "1.2.3"},
                            ],
                        }
                    ],
                    "versions": ["1.0.0", "1.1.0", "1.2.0"],
                }
            ],
            "severity": [
                {
                    "type": "CVSS_V3",
                    "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                }
            ],
        },
        {
            "id": "PYSEC-2024-42",
            "summary": "Denial of service in another-lib",
            "details": "Another vulnerability detail.",
            "aliases": [],
            "modified": "2024-01-14T12:00:00Z",
            "published": "2024-01-12T06:00:00Z",
            "references": [
                {"type": "WEB", "url": "https://example.com/vuln/2"},
            ],
            "affected": [
                {
                    "package": {
                        "ecosystem": "PyPI",
                        "name": "another-lib",
                    },
                    "ranges": [],
                    "versions": ["2.0.0"],
                }
            ],
            "severity": [],
        },
    ]
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="osv-pypi",
        type="osv",
        url="https://api.osv.dev/v1/query",
        weight=0.7,
        extra={"ecosystem": "PyPI"},
    )


@pytest.fixture()
def connector(config: SourceConfig) -> OsvConnector:
    return OsvConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_vulnerabilities(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_vuln_id(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["id"] == "GHSA-xxxx-yyyy-zzzz"
    assert items[1].raw_data["id"] == "PYSEC-2024-42"


@pytest.mark.asyncio
async def test_fetch_extracts_affected_packages(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    affected = items[0].raw_data["affected"]
    assert affected[0]["package"]["name"] == "example-package"
    assert affected[0]["package"]["ecosystem"] == "PyPI"


@pytest.mark.asyncio
async def test_fetch_extracts_severity(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["severity"][0]["type"] == "CVSS_V3"


@pytest.mark.asyncio
async def test_fetch_extracts_references(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items[0].raw_data["references"]) == 2


@pytest.mark.asyncio
async def test_dedupe_key_uses_vuln_id(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "osv:GHSA-xxxx-yyyy-zzzz"
    assert connector.dedupe_key(items[1]) == "osv:PYSEC-2024-42"


@pytest.mark.asyncio
async def test_fetch_creates_indicators(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    # First vuln has a CVE alias
    cve_ind = next((i for i in items[0].indicators if i["type"] == "cve"), None)
    assert cve_ind is not None
    assert cve_ind["value"] == "CVE-2024-1111"

    # Package indicator
    pkg_ind = next((i for i in items[0].indicators if i["type"] == "package"), None)
    assert pkg_ind is not None
    assert pkg_ind["value"] == "example-package"


@pytest.mark.asyncio
async def test_fetch_sets_title_and_summary(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert "GHSA-xxxx-yyyy-zzzz" in items[0].title
    assert "remote code execution" in items[0].summary.lower()


@pytest.mark.asyncio
async def test_fetch_sets_url(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_OSV_RESPONSE)
    )
    items = await connector.fetch()
    assert "GHSA-xxxx-yyyy-zzzz" in items[0].url


@pytest.mark.asyncio
async def test_fetch_empty_response(connector: OsvConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"vulns": []})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_no_vulns_key(connector: OsvConnector, respx_mock):
    """OSV returns empty object when no results."""
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_sends_ecosystem_in_body(connector: OsvConnector, respx_mock):
    route = respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"vulns": []})
    )
    await connector.fetch()
    request = route.calls[0].request
    import json

    body = json.loads(request.content)
    assert body["package"]["ecosystem"] == "PyPI"
