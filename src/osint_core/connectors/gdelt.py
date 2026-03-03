"""GDELT DOC 2.0 API connector."""

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class GdeltConnector(BaseConnector):
    """Fetches global event articles from the GDELT DOC 2.0 API."""

    async def fetch(self) -> list[RawItem]:
        params = dict(self.config.extra)

        async with httpx.AsyncClient() as client:
            resp = await client.get(self.config.url, params=params)
            resp.raise_for_status()

        data = resp.json()
        articles = data.get("articles") or []
        items: list[RawItem] = []

        for article in articles:
            items.append(self._parse_article(article))

        return items

    def _parse_article(self, article: dict[str, Any]) -> RawItem:
        url = article.get("url", "")
        title = article.get("title", "")
        seendate = article.get("seendate", "")

        occurred_at = None
        if seendate:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(
                    seendate, "%Y%m%dT%H%M%SZ"
                ).replace(tzinfo=UTC)

        return RawItem(
            title=title,
            url=url,
            raw_data=article,
            occurred_at=occurred_at,
            source_category="geopolitical",
        )

    def dedupe_key(self, item: RawItem) -> str:
        url = item.url or ""
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"gdelt:{url_hash}"
