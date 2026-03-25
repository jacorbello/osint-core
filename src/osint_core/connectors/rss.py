"""Generic RSS/Atom feed connector."""

import asyncio
import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any

import feedparser
import httpx
import structlog

from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RssConnector(BaseConnector):
    """Fetches and parses RSS/Atom feeds into RawItems."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._fetch_with_retries(client)

        if resp is None:
            return []

        feed = feedparser.parse(resp.text)
        items: list[RawItem] = []

        for entry in feed.entries:
            items.append(self._parse_entry(entry))

        return items

    async def _fetch_with_retries(self, client: httpx.AsyncClient) -> httpx.Response | None:
        """Fetch the feed URL with retry logic for transient HTTP errors."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(self.config.url)
            except httpx.TransportError as exc:
                logger.warning(
                    "rss_transport_error",
                    source_id=self.config.id,
                    url=self.config.url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                try:
                    retry_after = min(int(resp.headers.get("Retry-After", "10")), 60)
                except (ValueError, TypeError):
                    retry_after = 10
                logger.warning(
                    "rss_retryable_http_error",
                    source_id=self.config.id,
                    url=self.config.url,
                    status=resp.status_code,
                    retry_after=retry_after,
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(retry_after)
                continue

            if resp.is_error:
                logger.error(
                    "rss_http_error",
                    source_id=self.config.id,
                    url=self.config.url,
                    status=resp.status_code,
                )
                return None

            return resp

        logger.error(
            "rss_max_retries_exceeded",
            source_id=self.config.id,
            url=self.config.url,
            attempts=_MAX_RETRIES,
        )
        return None

    def _parse_entry(self, entry: Any) -> RawItem:
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
    def _parse_date(entry: Any) -> datetime | None:
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
                    return parsedate_to_datetime(raw).replace(tzinfo=UTC)  # type: ignore[no-any-return]
                except (ValueError, TypeError):
                    pass

        return None

    def dedupe_key(self, item: RawItem) -> str:
        link = item.url or ""
        link_hash = hashlib.sha256(link.encode()).hexdigest()[:16]
        return f"rss:{self.config.id}:{link_hash}"
