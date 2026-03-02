from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SourceConfig:
    id: str
    type: str
    url: str
    weight: float
    extra: dict = field(default_factory=dict)


@dataclass
class RawItem:
    title: str
    url: str
    raw_data: dict
    summary: str = ""
    occurred_at: datetime | None = None
    severity: str | None = None
    indicators: list[dict] = field(default_factory=list)


class BaseConnector(ABC):
    def __init__(self, config: SourceConfig):
        self.config = config

    @abstractmethod
    async def fetch(self) -> list[RawItem]:
        ...

    @abstractmethod
    def dedupe_key(self, item: RawItem) -> str:
        ...
