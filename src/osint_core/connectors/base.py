from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SourceConfig:
    id: str
    type: str
    url: str
    weight: float
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawItem:
    title: str
    url: str
    raw_data: dict[str, Any]
    summary: str = ""
    occurred_at: datetime | None = None
    severity: str | None = None
    indicators: list[dict[str, Any]] = field(default_factory=list)
    # Geographic fields
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    region: str | None = None
    source_category: str | None = None
    actors: list[dict[str, Any]] = field(default_factory=list)
    event_type: str | None = None
    event_subtype: str | None = None
    fatalities: int | None = None


class BaseConnector(ABC):
    def __init__(self, config: SourceConfig):
        self.config = config

    @abstractmethod
    async def fetch(self) -> list[RawItem]:
        ...

    @abstractmethod
    def dedupe_key(self, item: RawItem) -> str:
        ...
