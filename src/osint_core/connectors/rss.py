"""Generic RSS/Atom feed connector."""

import asyncio
import hashlib
import ipaddress
import socket
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
import structlog

from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

_MAX_RETRIES = 3
_MAX_REDIRECTS = 5
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_safe_redirect_target(url: str) -> bool:
    """Return True if the URL is safe to follow (not private/loopback, HTTP(S) only)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Resolve hostname and check all addresses against private/loopback ranges
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False

    return True


class RssConnector(BaseConnector):
    """Fetches and parses RSS/Atom feeds into RawItems."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await self._fetch_with_safe_redirects(client)

        if resp is None:
            return []

        feed = feedparser.parse(resp.text)
        items: list[RawItem] = []

        for entry in feed.entries:
            items.append(self._parse_entry(entry))

        return items

    async def _fetch_with_safe_redirects(
        self, client: httpx.AsyncClient
    ) -> httpx.Response | None:
        """Fetch the feed, manually following redirects with SSRF protection.

        Blocks redirects to private/loopback IPs and non-HTTP(S) schemes,
        and caps the redirect chain length.
        """
        current_url = self.config.url
        for _ in range(_MAX_REDIRECTS):
            resp = await self._fetch_with_retries(client, current_url)
            if resp is None:
                return None

            if resp.status_code not in _REDIRECT_STATUS_CODES:
                return resp

            location = resp.headers.get("Location")
            if not location:
                return resp

            redirect_url = urljoin(current_url, location)

            if not _is_safe_redirect_target(redirect_url):
                logger.warning(
                    "rss_redirect_blocked",
                    source_id=self.config.id,
                    original_url=self.config.url,
                    redirect_url=redirect_url,
                    reason="redirect target is private, loopback, or non-HTTP(S)",
                )
                return None

            current_url = redirect_url

        logger.error(
            "rss_too_many_redirects",
            source_id=self.config.id,
            url=self.config.url,
            max_redirects=_MAX_REDIRECTS,
        )
        return None

    async def _fetch_with_retries(
        self, client: httpx.AsyncClient, url: str
    ) -> httpx.Response | None:
        """Fetch a URL with retry logic for transient HTTP errors."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(url)
            except httpx.TransportError as exc:
                logger.warning(
                    "rss_transport_error",
                    source_id=self.config.id,
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raw_retry = resp.headers.get("Retry-After")
                if raw_retry is not None:
                    try:
                        delay = min(int(raw_retry), 60)
                    except (ValueError, TypeError):
                        delay = 2 ** attempt
                else:
                    delay = 2 ** attempt  # exponential backoff when no header
                logger.warning(
                    "rss_retryable_http_error",
                    source_id=self.config.id,
                    url=url,
                    status=resp.status_code,
                    retry_after=delay,
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                continue

            if resp.is_error:
                logger.error(
                    "rss_http_error",
                    source_id=self.config.id,
                    url=url,
                    status=resp.status_code,
                )
                return None

            return resp

        logger.error(
            "rss_max_retries_exceeded",
            source_id=self.config.id,
            url=url,
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
                    return parsedate_to_datetime(raw).replace(tzinfo=UTC)  # type: ignore[return-value]
                except (ValueError, TypeError):
                    pass

        return None

    def dedupe_key(self, item: RawItem) -> str:
        link = item.url or ""
        link_hash = hashlib.sha256(link.encode()).hexdigest()[:16]
        return f"rss:{self.config.id}:{link_hash}"
