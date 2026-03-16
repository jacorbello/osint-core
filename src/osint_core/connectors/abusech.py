"""Abuse.ch connectors: MalwareBazaar and FeodoTracker."""
from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime

import httpx

from .base import BaseConnector, RawItem

_COUNTRY_ISO2_TO_ISO3 = {
    "US": "USA", "GB": "GBR", "CN": "CHN", "RU": "RUS", "DE": "DEU",
    "FR": "FRA", "NL": "NLD", "JP": "JPN", "KR": "KOR", "IN": "IND",
    "BR": "BRA", "CA": "CAN", "AU": "AUS", "IT": "ITA", "ES": "ESP",
}


class MalwareBazaarConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.config.url,
                data={"query": "get_recent", "selector": "time"},
            )
            resp.raise_for_status()
        samples = resp.json().get("data") or []
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(s) for s in samples[:max_items]]

    def _parse(self, sample: dict) -> RawItem:
        sig = sample.get("signature") or "Unknown"
        sha = sample.get("sha256_hash", "")
        seen = sample.get("first_seen", "")
        occurred_at = None
        if seen:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(seen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return RawItem(
            title=f"Malware sample: {sig} ({sample.get('file_type', '')})",
            url=f"https://bazaar.abuse.ch/sample/{sha}/",
            raw_data=sample,
            summary=f"Tags: {', '.join(sample.get('tags') or [])}",
            occurred_at=occurred_at,
            indicators=[{"type": "sha256", "value": sha}],
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        sha = item.raw_data.get("sha256_hash", item.url)
        return f"mb:{sha[:16]}"


class FeodoTrackerConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url)
            resp.raise_for_status()
        entries = resp.json() if isinstance(resp.json(), list) else []
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(e) for e in entries[:max_items]]

    def _parse(self, entry: dict) -> RawItem:
        ip = entry.get("ip_address", "")
        malware = entry.get("malware", "Unknown")
        seen = entry.get("first_seen", "")
        occurred_at = None
        if seen:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(seen, "%Y-%m-%d").replace(tzinfo=UTC)
        country_iso2 = entry.get("country", "")
        country_code = _COUNTRY_ISO2_TO_ISO3.get(country_iso2, country_iso2)
        return RawItem(
            title=f"C2 server: {ip}:{entry.get('port', '')} ({malware})",
            url=f"https://feodotracker.abuse.ch/browse/host/{ip}/",
            raw_data=entry,
            occurred_at=occurred_at,
            indicators=[{"type": "ip", "value": ip}],
            source_category="cyber",
            country_code=country_code if len(country_code) == 3 else None,
        )

    def dedupe_key(self, item: RawItem) -> str:
        ip = item.raw_data.get("ip_address", item.url)
        return f"feodo:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
