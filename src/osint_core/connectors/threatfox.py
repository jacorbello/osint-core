"""ThreatFox IOC feed connector."""

import contextlib
from datetime import UTC, datetime

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class ThreatFoxConnector(BaseConnector):
    """Fetches recent IOCs from the ThreatFox API."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.config.url, json={"query": "get_iocs", "days": 1}
            )
            resp.raise_for_status()

        data = resp.json()
        entries = data.get("data") or []
        items: list[RawItem] = []

        for entry in entries:
            items.append(self._parse_entry(entry))

        return items

    def _parse_entry(self, entry: dict) -> RawItem:
        ioc_id = str(entry["id"])
        ioc_value = entry.get("ioc", "")
        ioc_type = entry.get("ioc_type", "")
        threat_type = entry.get("threat_type", "")
        malware = entry.get("malware_printable", "")
        confidence = entry.get("confidence_level", 0)
        first_seen = entry.get("first_seen", "")

        occurred_at = None
        if first_seen:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(
                    first_seen, "%Y-%m-%d %H:%M:%S %Z"
                ).replace(tzinfo=UTC)

        indicators: list[dict] = [{"type": ioc_type, "value": ioc_value}]

        return RawItem(
            title=f"{malware} - {threat_type} ({ioc_type})",
            url=entry.get("malware_malpedia", "")
            or f"https://threatfox.abuse.ch/ioc/{ioc_id}/",
            summary=(
                f"IOC: {ioc_value} | Type: {ioc_type} | Threat: {threat_type} | "
                f"Malware: {malware} | Confidence: {confidence}%"
            ),
            raw_data=entry,
            occurred_at=occurred_at,
            indicators=indicators,
        )

    def dedupe_key(self, item: RawItem) -> str:
        return f"threatfox:{item.raw_data['id']}"
