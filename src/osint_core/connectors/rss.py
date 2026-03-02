"""Generic RSS/Atom feed connector."""

import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser
import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class RssConnector(BaseConnector):
    """Fetches and parses RSS/Atom feeds into RawItems."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(self.config.url)
            resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        items: list[RawItem] = []

        for entry in feed.entries:
            items.append(self._parse_entry(entry))

        return items

    def _parse_entry(self, entry) -> RawItem:
        title = getattr(entry, "title", "")
        link = getattr(entry, "link", "")
        summary = getattr(entry, "summary", getattr(entry, "description", ""))
        occurred_at = self._parse_date(entry)

        raw_data = {
            "title": title,
            "link": link,
            "summary": summary,
        }
        # Include any additional standard fields
        for field in ("id", "author", "published", "updated", "tags"):
            val = getattr(entry, field, None)
            if val is not None:
                raw_data[field] = val

        return RawItem(
            title=title,
            url=link,
            summary=summary,
            raw_data=raw_data,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _parse_date(entry) -> datetime | None:
        # Try published_parsed first, then updated_parsed
        for attr in ("published_parsed", "updated_parsed"):
            parsed: struct_time | None = getattr(entry, attr, None)
            if parsed:
                try:
                    return datetime(*parsed[:6], tzinfo=UTC)
                except (ValueError, TypeError):
                    pass

        # Fallback: try raw string parsing
        for attr in ("published", "updated"):
            raw = getattr(entry, attr, None)
            if raw:
                try:
                    return parsedate_to_datetime(raw).replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    pass

        return None

    def dedupe_key(self, item: RawItem) -> str:
        link = item.url or ""
        link_hash = hashlib.sha256(link.encode()).hexdigest()[:16]
        return f"rss:{self.config.id}:{link_hash}"
