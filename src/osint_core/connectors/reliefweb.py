"""ReliefWeb API v2 connector for humanitarian reports."""

from datetime import datetime
from typing import Any

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class ReliefWebConnector(BaseConnector):
    """Fetches humanitarian reports from the ReliefWeb API v2."""

    async def fetch(self) -> list[RawItem]:
        appname = self.config.extra.get("appname", "osint-core")
        country_filter = self.config.extra.get("countries")

        body: dict[str, Any] = {
            "fields": {
                "include": [
                    "title",
                    "body",
                    "date.created",
                    "url",
                    "primary_country.iso3",
                    "primary_country.name",
                    "disaster_type.name",
                    "source.name",
                    "status",
                ],
            },
            "sort": ["date.created:desc"],
            "limit": 50,
        }

        if country_filter:
            body["filter"] = {
                "field": "primary_country.iso3",
                "value": country_filter,
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.config.url,
                params={"appname": appname},
                json=body,
            )
            resp.raise_for_status()

        data = resp.json()
        items: list[RawItem] = []

        for entry in data.get("data", []):
            items.append(self._parse_entry(entry))

        return items

    def _parse_entry(self, entry: dict[str, Any]) -> RawItem:
        report_id = str(entry.get("id", ""))
        fields = entry.get("fields", {})

        title = fields.get("title", "")
        body = fields.get("body", "")
        summary = body[:500] if body else ""
        url = fields.get("url", "")

        occurred_at = None
        date_info = fields.get("date", {})
        created = date_info.get("created", "")
        if created:
            occurred_at = datetime.fromisoformat(created)

        primary_country = fields.get("primary_country", {})
        country_code = primary_country.get("iso3")

        raw_data = entry
        raw_data["_report_id"] = report_id

        return RawItem(
            title=title,
            url=url,
            summary=summary,
            raw_data=raw_data,
            occurred_at=occurred_at,
            country_code=country_code,
            source_category="humanitarian",
        )

    def dedupe_key(self, item: RawItem) -> str:
        report_id = item.raw_data.get("_report_id", item.raw_data.get("id", ""))
        return f"reliefweb:{report_id}"
