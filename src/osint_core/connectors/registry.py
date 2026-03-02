from osint_core.connectors.base import BaseConnector, SourceConfig


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, type[BaseConnector]] = {}

    def register(self, source_type: str, cls: type[BaseConnector]) -> None:
        self._connectors[source_type] = cls

    def get(self, source_type: str, config: SourceConfig) -> BaseConnector:
        if source_type not in self._connectors:
            raise KeyError(f"No connector registered for type: {source_type}")
        return self._connectors[source_type](config)

    def has(self, source_type: str) -> bool:
        return source_type in self._connectors
