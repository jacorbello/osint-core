"""GDELT DOC 2.0 API connector with geographic and language filtering."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from .base import BaseConnector, RawItem

logger = structlog.get_logger()

_COUNTRY_MAP: dict[str, str] = {
    "United States": "USA", "United Kingdom": "GBR", "China": "CHN",
    "Russia": "RUS", "France": "FRA", "Germany": "DEU", "Japan": "JPN",
    "South Korea": "KOR", "India": "IND", "Brazil": "BRA", "Canada": "CAN",
    "Australia": "AUS", "Mexico": "MEX", "Spain": "ESP", "Italy": "ITA",
    "Turkey": "TUR", "Iran": "IRN", "Iraq": "IRQ", "Israel": "ISR",
    "Ukraine": "UKR", "Poland": "POL", "Nigeria": "NGA", "Egypt": "EGY",
    "Saudi Arabia": "SAU", "Pakistan": "PAK", "Indonesia": "IDN",
    "Argentina": "ARG", "Colombia": "COL", "South Africa": "ZAF",
    "Thailand": "THA", "Vietnam": "VNM", "Philippines": "PHL",
    "Taiwan": "TWN", "Netherlands": "NLD", "Belgium": "BEL",
    "Sweden": "SWE", "Norway": "NOR", "Denmark": "DNK", "Finland": "FIN",
    "Switzerland": "CHE", "Austria": "AUT", "Ireland": "IRL",
    "Portugal": "PRT", "Greece": "GRC", "Czech Republic": "CZE",
    "Romania": "ROU", "Hungary": "HUN", "Syria": "SYR", "Yemen": "YEM",
    "Afghanistan": "AFG", "Belarus": "BLR", "Georgia": "GEO",
    "Singapore": "SGP", "Malaysia": "MYS", "Chile": "CHL", "Peru": "PER",
}


class GdeltConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        query = self._build_query()
        lookback_hours = self.config.extra.get("lookback_hours", 4)
        params = {
            "query": query,
            "mode": self.config.extra.get("mode", "ArtList"),
            "maxrecords": str(self.config.extra.get("maxrecords", "100")),
            "format": "json",
            "timespan": f"{int(lookback_hours * 60)}min",
        }
        timespan = self.config.extra.get("timespan")
        if timespan:
            params["timespan"] = timespan

        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                resp = await client.get(self.config.url, params=params)
                if resp.status_code in (429, 503):
                    retry_after = min(
                        int(resp.headers.get("Retry-After", "10")), 60,
                    )
                    logger.warning(
                        "gdelt_rate_limited",
                        status=resp.status_code,
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                break
            else:
                logger.error("gdelt_max_retries_exceeded", attempts=3)
                return []

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "gdelt_non_json_response",
                status=resp.status_code,
                body_preview=resp.text[:200],
            )
            return []
        articles = data.get("articles", [])

        max_per_domain = self.config.extra.get("max_per_domain")
        if max_per_domain:
            articles = self._cap_per_domain(articles, max_per_domain)

        max_items = self.config.extra.get("max_items", 100)
        articles = articles[:max_items]

        return [self._parse_article(a) for a in articles if a.get("title")]

    def _build_query(self) -> str:
        base = self.config.extra.get("query", "")
        geo_terms = self.config.extra.get("geo_terms")
        langs = self.config.extra.get("preferred_languages", [])

        query = base
        if geo_terms:
            query = f"({base}) AND ({geo_terms})"

        if langs:
            lang_parts = " OR ".join(f"sourcelang:{lang}" for lang in langs)
            query = f"({query}) AND ({lang_parts})"

        return str(query)

    def _cap_per_domain(self, articles: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        result = []
        for article in articles:
            domain = article.get("domain", "")
            if counts[domain] < cap:
                result.append(article)
                counts[domain] += 1
        return result

    def _parse_article(self, article: dict[str, Any]) -> RawItem:
        seen = article.get("seendate", "")
        occurred_at = None
        if seen:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)

        country_name = article.get("sourcecountry", "")
        country_code = _COUNTRY_MAP.get(country_name)

        return RawItem(
            title=article.get("title", ""),
            url=article.get("url", ""),
            raw_data=article,
            source_category="geopolitical",
            occurred_at=occurred_at,
            country_code=country_code,
        )

    def dedupe_key(self, item: RawItem) -> str:
        url_hash = hashlib.sha256(item.url.encode()).hexdigest()[:16]
        return f"gdelt:{url_hash}"
