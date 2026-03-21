"""Paste site monitor connector.

Monitors public paste APIs for leaked credentials and IOCs.  Content is
automatically run through the indicator extraction service to surface
IPs, domains, hashes, CVEs, and URLs.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from osint_core.connectors.base import BaseConnector, RawItem
from osint_core.services.indicators import extract_indicators

_DEFAULT_API_URL = "https://psbdmp.ws/api/v3/search/"
_DEFAULT_LOOKBACK_HOURS = 24
_CONTENT_EXCERPT_LENGTH = 2000
_RAW_DATA_CONTENT_LIMIT = 500


class PasteSiteConnector(BaseConnector):
    """Fetches pastes from a paste-site search API and extracts IOCs."""

    async def fetch(self) -> list[RawItem]:
        keywords: list[str] = self.config.extra.get("keywords", [])
        max_items: int = int(self.config.extra.get("max_items", 100))
        timeout: int = int(self.config.extra.get("timeout", 30))
        lookback_hours: int = int(
            self.config.extra.get("lookback_hours", _DEFAULT_LOOKBACK_HOURS)
        )

        if not keywords:
            return []

        if lookback_hours < 1:
            raise ValueError(
                f"lookback_hours must be >= 1, got {lookback_hours}"
            )

        cutoff = datetime.now(tz=UTC) - timedelta(hours=lookback_hours)

        all_items: list[RawItem] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=timeout) as client:
            for keyword in keywords:
                raw_pastes = await self._search_keyword(
                    client, keyword, seen_ids
                )
                for paste in raw_pastes:
                    # Filter by lookback window before running full
                    # parsing/indicator extraction to avoid unnecessary work.
                    # Keep pastes with no timestamp (missing dates should not
                    # cause data loss).
                    ts = self._parse_timestamp(paste)
                    if ts is not None and ts < cutoff:
                        continue
                    all_items.append(self._parse_paste(paste, occurred_at=ts))
                    if len(all_items) >= max_items:
                        break
                if len(all_items) >= max_items:
                    break

        return all_items[:max_items]

    async def _search_keyword(
        self,
        client: httpx.AsyncClient,
        keyword: str,
        seen_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Return deduplicated raw paste dicts for *keyword*."""
        # URL-encode the keyword to handle spaces and special characters
        base_url = (self.config.url or _DEFAULT_API_URL).rstrip("/")
        url = f"{base_url}/{quote(keyword, safe='')}"
        resp = await client.get(url)
        resp.raise_for_status()

        data = resp.json()
        pastes: list[dict[str, Any]] = data if isinstance(data, list) else data.get("data", [])

        results: list[dict[str, Any]] = []
        for paste in pastes:
            paste_id = paste.get("id", paste.get("key", ""))
            if not paste_id or paste_id in seen_ids:
                continue
            seen_ids.add(paste_id)
            results.append(paste)

        return results

    @staticmethod
    def _parse_timestamp(paste: dict[str, Any]) -> datetime | None:
        """Extract and normalise the paste timestamp to a UTC datetime."""
        timestamp_raw = paste.get("time", paste.get("date", paste.get("timestamp", "")))
        if timestamp_raw is None or timestamp_raw == "":
            return None
        with contextlib.suppress(ValueError, TypeError, OSError):
            if isinstance(timestamp_raw, (int, float)):
                return datetime.fromtimestamp(timestamp_raw, tz=UTC)
            parsed = datetime.fromisoformat(str(timestamp_raw))
            parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
            return parsed
        return None

    def _parse_paste(
        self,
        paste: dict[str, Any],
        *,
        occurred_at: datetime | None = None,
    ) -> RawItem:
        paste_id = paste.get("id", paste.get("key", ""))
        title = paste.get("title", "") or f"Paste {paste_id}"
        content = paste.get("content", paste.get("text", ""))
        author = paste.get("author", paste.get("user", "")) or "anonymous"

        # Use the pre-parsed timestamp when provided to avoid redundant
        # parsing; fall back to parsing here for standalone calls.
        if occurred_at is None:
            occurred_at = self._parse_timestamp(paste)

        # Run indicator extraction on the paste content.
        # Note: the ingest pipeline re-extracts from summary/title, so storing
        # indicators here is supplementary for direct API consumers.
        indicators = extract_indicators(content) if content else []

        excerpt = content[:_CONTENT_EXCERPT_LENGTH] if content else ""

        paste_url = paste.get("url", f"https://pastebin.com/{paste_id}")

        # Store only a bounded subset of paste data to avoid persisting
        # large content or sensitive credentials in event metadata.
        raw_data: dict[str, Any] = {
            "id": paste_id,
            "title": title,
            "author": author,
            "url": paste_url,
            "content_excerpt": content[:_RAW_DATA_CONTENT_LIMIT] if content else "",
            "content_length": len(content) if content else 0,
            "timestamp": paste.get("time", paste.get("date", paste.get("timestamp", ""))),
        }

        return RawItem(
            title=title,
            url=paste_url,
            summary=f"Author: {author} | Excerpt: {excerpt[:200]}",
            raw_data=raw_data,
            occurred_at=occurred_at,
            indicators=indicators,
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        paste_id = item.raw_data.get("id", item.url)
        return f"pastebin:{hashlib.sha256(str(paste_id).encode()).hexdigest()[:16]}"
