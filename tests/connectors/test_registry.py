import pytest

from osint_core.connectors.base import BaseConnector, RawItem, SourceConfig
from osint_core.connectors.registry import ConnectorRegistry


class FakeConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        return [RawItem(title="Test", url="https://example.com", raw_data={})]

    def dedupe_key(self, item: RawItem) -> str:
        return f"fake:{item.url}"


def test_register_and_get():
    registry = ConnectorRegistry()
    registry.register("fake_type", FakeConnector)
    config = SourceConfig(id="test", type="fake_type", url="https://example.com", weight=1.0)
    connector = registry.get("fake_type", config)
    assert isinstance(connector, FakeConnector)


def test_get_unregistered_raises():
    registry = ConnectorRegistry()
    config = SourceConfig(id="test", type="unknown", url="", weight=1.0)
    with pytest.raises(KeyError):
        registry.get("unknown", config)
