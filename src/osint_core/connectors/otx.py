"""AlienVault OTX pulse feed connector."""
from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx

from .base import BaseConnector, RawItem


class OtxConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        api_key = self.config.extra.get("api_key", "")
        headers = {"X-OTX-API-KEY": api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, headers=headers)
            resp.raise_for_status()
        pulses = resp.json().get("results", [])
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse_pulse(p) for p in pulses[:max_items]]

    def _parse_pulse(self, pulse: dict[str, Any]) -> RawItem:
        created = pulse.get("created", "")
        occurred_at = None
        if created:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.fromisoformat(created).replace(tzinfo=UTC)
        indicators = [
            {"type": i["type"], "value": i["indicator"]}
            for i in pulse.get("indicators", [])
        ]
        return RawItem(
            title=pulse.get("name", ""),
            url=f"https://otx.alienvault.com/pulse/{pulse.get('id', '')}",
            raw_data=pulse,
            summary=pulse.get("description", ""),
            occurred_at=occurred_at,
            indicators=indicators,
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        pulse_id = item.raw_data.get("id", item.url)
        return f"otx:{hashlib.sha256(pulse_id.encode()).hexdigest()[:16]}"
