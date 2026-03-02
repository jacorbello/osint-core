"""Tests for the ThreatFox IOC feed connector."""

from datetime import UTC, datetime

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.threatfox import ThreatFoxConnector

SAMPLE_THREATFOX_RESPONSE = {
    "query_status": "ok",
    "data": [
        {
            "id": "100001",
            "ioc": "http://evil.example.com/malware.bin",
            "threat_type": "payload_delivery",
            "threat_type_desc": "Indicator that identifies a malware distribution site",
            "ioc_type": "url",
            "ioc_type_desc": "URL that distributes malware",
            "malware": "win.cobalt_strike",
            "malware_printable": "Cobalt Strike",
            "malware_alias": None,
            "malware_malpedia": "https://malpedia.caad.fkie.fraunhofer.de/details/win.cobalt_strike",
            "confidence_level": 90,
            "first_seen": "2024-01-15 08:00:00 UTC",
            "last_seen": None,
            "reference": "https://example.com/report/1",
            "reporter": "researcher1",
            "tags": ["cobalt-strike", "c2"],
        },
        {
            "id": "100002",
            "ioc": "192.168.100.50:443",
            "threat_type": "botnet_cc",
            "threat_type_desc": "Indicator that identifies a botnet command&control server",
            "ioc_type": "ip:port",
            "ioc_type_desc": "Combination of ip and port",
            "malware": "win.emotet",
            "malware_printable": "Emotet",
            "malware_alias": "Heodo",
            "malware_malpedia": "https://malpedia.caad.fkie.fraunhofer.de/details/win.emotet",
            "confidence_level": 75,
            "first_seen": "2024-01-14 12:00:00 UTC",
            "last_seen": "2024-01-15 06:00:00 UTC",
            "reference": None,
            "reporter": "researcher2",
            "tags": ["emotet", "botnet"],
        },
    ],
}


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="threatfox",
        type="threatfox",
        url="https://threatfox-api.abuse.ch/api/v1/",
        weight=0.8,
    )


@pytest.fixture()
def connector(config: SourceConfig) -> ThreatFoxConnector:
    return ThreatFoxConnector(config)


@pytest.mark.asyncio
async def test_fetch_parses_iocs(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_ioc_type(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["ioc_type"] == "url"
    assert items[1].raw_data["ioc_type"] == "ip:port"


@pytest.mark.asyncio
async def test_fetch_extracts_ioc_value(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["ioc"] == "http://evil.example.com/malware.bin"
    assert items[1].raw_data["ioc"] == "192.168.100.50:443"


@pytest.mark.asyncio
async def test_fetch_extracts_threat_type(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["threat_type"] == "payload_delivery"
    assert items[1].raw_data["threat_type"] == "botnet_cc"


@pytest.mark.asyncio
async def test_fetch_extracts_malware(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["malware_printable"] == "Cobalt Strike"
    assert items[1].raw_data["malware_printable"] == "Emotet"


@pytest.mark.asyncio
async def test_fetch_extracts_confidence(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].raw_data["confidence_level"] == 90
    assert items[1].raw_data["confidence_level"] == 75


@pytest.mark.asyncio
async def test_dedupe_key_uses_ioc_id(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) == "threatfox:100001"
    assert connector.dedupe_key(items[1]) == "threatfox:100002"


@pytest.mark.asyncio
async def test_fetch_creates_indicators(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    # First item is a URL IOC
    ioc_ind = next(i for i in items[0].indicators if i["type"] == "url")
    assert ioc_ind["value"] == "http://evil.example.com/malware.bin"

    # Second item is an ip:port IOC
    ioc_ind2 = next(i for i in items[1].indicators if i["type"] == "ip:port")
    assert ioc_ind2["value"] == "192.168.100.50:443"


@pytest.mark.asyncio
async def test_fetch_sets_title(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert "Cobalt Strike" in items[0].title
    assert "Emotet" in items[1].title


@pytest.mark.asyncio
async def test_fetch_sets_occurred_at(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_THREATFOX_RESPONSE)
    )
    items = await connector.fetch()
    assert items[0].occurred_at == datetime(2024, 1, 15, 8, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_fetch_empty_data(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(200, json={"query_status": "ok", "data": []})
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_no_results(connector: ThreatFoxConnector, respx_mock):
    respx_mock.post(connector.config.url).mock(
        return_value=httpx.Response(
            200, json={"query_status": "no_result", "data": None}
        )
    )
    items = await connector.fetch()
    assert items == []
