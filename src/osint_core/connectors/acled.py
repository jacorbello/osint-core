"""ACLED conflict event data connector."""
from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime

import httpx

from .base import BaseConnector, RawItem


class AcledConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        params = {
            "key": self.config.extra.get("api_key", ""),
            "email": self.config.extra.get("email", ""),
            "limit": str(self.config.extra.get("max_items", 100)),
        }
        country = self.config.extra.get("country")
        if country:
            params["country"] = country
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, params=params)
            resp.raise_for_status()
        events = resp.json().get("data", [])
        return [self._parse(e) for e in events if e.get("notes")]

    def _parse(self, event: dict) -> RawItem:
        date_str = event.get("event_date", "")
        occurred_at = None
        if date_str:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        lat = event.get("latitude")
        lon = event.get("longitude")
        fatalities_raw = event.get("fatalities", "0")
        return RawItem(
            title=f"{event.get('event_type', '')}: {event.get('notes', '')[:100]}",
            url=(
                "https://acleddata.com/data-export-tool/"
                f"?event_id={event.get('event_id_cnty', '')}"
            ),
            raw_data=event,
            summary=event.get("notes", ""),
            occurred_at=occurred_at,
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
            country_code=event.get("iso3"),
            source_category="geopolitical",
            event_type=event.get("event_type"),
            fatalities=int(fatalities_raw) if fatalities_raw else 0,
            actors=(
                [{"name": event.get("actor1", ""), "role": "primary"}]
                if event.get("actor1")
                else []
            ),
        )

    def dedupe_key(self, item: RawItem) -> str:
        eid = item.raw_data.get("event_id_cnty", item.url)
        return f"acled:{hashlib.sha256(eid.encode()).hexdigest()[:16]}"
