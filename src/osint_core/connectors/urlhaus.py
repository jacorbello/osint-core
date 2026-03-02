"""URLhaus malicious URL feed connector."""

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class UrlhausConnector(BaseConnector):
    """Fetches recent malicious URLs from the URLhaus API."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.config.url, data={"query": "recent", "limit": 100})
            resp.raise_for_status()

        data = resp.json()
        items: list[RawItem] = []

        for entry in data.get("urls", []):
            items.append(self._parse_entry(entry))

        return items

    def _parse_entry(self, entry: dict[str, Any]) -> RawItem:
        mal_url = entry.get("url", "")
        host = entry.get("host", "")
        if not host:
            host = urlparse(mal_url).hostname or ""
        threat = entry.get("threat", "")
        tags = entry.get("tags", [])
        date_added = entry.get("date_added", "")

        occurred_at = None
        if date_added:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(
                    date_added, "%Y-%m-%d %H:%M:%S %Z"
                ).replace(tzinfo=UTC)

        indicators: list[dict[str, Any]] = [{"type": "url", "value": mal_url}]
        if host:
            indicators.append({"type": "domain", "value": host})

        return RawItem(
            title=f"{threat} - {host}" if threat else host,
            url=entry.get("urlhaus_reference", ""),
            summary=f"Malicious URL: {mal_url} (threat: {threat}, tags: {', '.join(tags or [])})",
            raw_data=entry,
            occurred_at=occurred_at,
            indicators=indicators,
        )

    def dedupe_key(self, item: RawItem) -> str:
        url_hash = hashlib.sha256(item.raw_data["url"].encode()).hexdigest()[:16]
        return f"urlhaus:{url_hash}"
