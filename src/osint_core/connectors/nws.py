"""NWS (National Weather Service) alerts connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem

_NWS_SEVERITY_MAP = {
    "Extreme": "critical",
    "Severe": "high",
    "Moderate": "medium",
    "Minor": "low",
    "Unknown": "info",
}


class NwsConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        params = {}
        zone = self.config.extra.get("zone")
        if zone:
            params["zone"] = zone
        headers = {"User-Agent": "(osint-core, admin@corbello.io)", "Accept": "application/geo+json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, params=params, headers=headers)
            resp.raise_for_status()
        features = resp.json().get("features", [])
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(f) for f in features[:max_items]]

    def _parse(self, feature: dict) -> RawItem:
        props = feature.get("properties", {})
        onset = props.get("onset", "")
        occurred_at = None
        if onset:
            try:
                occurred_at = datetime.fromisoformat(onset).astimezone(timezone.utc)
            except ValueError:
                pass
        nws_severity = props.get("severity", "Unknown")
        return RawItem(
            title=props.get("headline", props.get("event", "")),
            url=f"https://alerts.weather.gov/search?id={feature.get('id', '')}",
            raw_data=props,
            summary=props.get("description", "")[:500],
            occurred_at=occurred_at,
            severity=_NWS_SEVERITY_MAP.get(nws_severity, "info"),
            source_category="weather",
            country_code="USA",
        )

    def dedupe_key(self, item: RawItem) -> str:
        alert_id = item.raw_data.get("id", item.url)
        return f"nws:{hashlib.sha256(str(alert_id).encode()).hexdigest()[:16]}"
