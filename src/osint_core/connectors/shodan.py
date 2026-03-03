"""Shodan search API connector."""

import hashlib
from typing import Any

import httpx

from osint_core.connectors.base import BaseConnector, RawItem
from osint_core.services.geo import iso2_to_iso3


class ShodanConnector(BaseConnector):
    """Fetches infrastructure data from the Shodan search API."""

    def _resolve_api_key(self) -> str:
        """Return the API key from source config or global settings."""
        key: str = self.config.extra.get("api_key", "")
        if not key:
            from osint_core.config import settings

            key = settings.shodan_api_key
        if not key:
            raise ValueError(
                "Shodan API key not configured in source params or OSINT_SHODAN_API_KEY"
            )
        return key

    async def fetch(self) -> list[RawItem]:
        params = {
            "key": self._resolve_api_key(),
            "query": self.config.extra["query"],
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(self.config.url, params=params)
            resp.raise_for_status()

        data = resp.json()
        matches = data.get("matches") or []
        items: list[RawItem] = []

        for match in matches:
            items.append(self._parse_match(match))

        return items

    def _parse_match(self, match: dict[str, Any]) -> RawItem:
        ip_str = match.get("ip_str", "")
        port = match.get("port", "")
        product = match.get("product", "") or ""
        version = match.get("version", "") or ""
        location = match.get("location") or {}
        vulns = match.get("vulns") or []
        hostnames = match.get("hostnames") or []

        title = f"{ip_str}:{port} — {product} {version}".strip()

        indicators: list[dict[str, Any]] = [{"type": "ip", "value": ip_str}]

        for vuln in vulns:
            indicators.append({"type": "cve", "value": vuln})

        for hostname in hostnames:
            indicators.append({"type": "domain", "value": hostname})

        # Shodan returns ISO-2 country codes; normalize to ISO-3 for
        # consistency with the rest of the platform (watches, geo service).
        raw_cc = location.get("country_code")
        country_code = iso2_to_iso3(raw_cc) if raw_cc else None

        return RawItem(
            title=title,
            url=f"https://www.shodan.io/host/{ip_str}",
            summary=(
                f"IP: {ip_str} | Port: {port} | Product: {product} {version} | "
                f"Org: {match.get('org', '')} | ASN: {match.get('asn', '')}"
            ),
            raw_data=match,
            indicators=indicators,
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            country_code=country_code,
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        ip_str = item.raw_data.get("ip_str", "")
        port = item.raw_data.get("port", "")
        timestamp = item.raw_data.get("timestamp", "")
        raw = f"{ip_str}:{port}:{timestamp}"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"shodan:{key_hash}"
