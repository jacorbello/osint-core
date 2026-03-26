"""NVD API 2.0 feed connector."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

# Keys consumed by the connector, NOT passed to the NVD API.
_CONNECTOR_KEYS = frozenset({"lookback_hours", "max_pages", "max_items"})


class NvdConnector(BaseConnector):
    """Fetches recent CVEs from the NVD API 2.0 with pagination support."""

    RESULTS_PER_PAGE = 2000

    async def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        start_index = 0
        max_pages = int(self.config.extra.get("max_pages", 5))
        pages_fetched = 0

        params: dict[str, Any] = {"resultsPerPage": self.RESULTS_PER_PAGE}

        # Time-window filter — only fetch recently modified CVEs
        lookback_hours = self.config.extra.get("lookback_hours")
        if lookback_hours:
            start_date = datetime.now(UTC) - timedelta(hours=int(lookback_hours))
            params["lastModStartDate"] = start_date.isoformat()
            params["lastModEndDate"] = datetime.now(UTC).isoformat()

        # Pass through API-level params, stripping connector-only keys
        for key, value in self.config.extra.items():
            if key not in _CONNECTOR_KEYS:
                params[key] = value

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params["startIndex"] = start_index

                resp = await client.get(self.config.url, params=params)
                resp.raise_for_status()
                data = resp.json()

                vulnerabilities = data.get("vulnerabilities", [])
                for entry in vulnerabilities:
                    cve = entry["cve"]
                    items.append(self._parse_cve(cve))

                total = data.get("totalResults", 0)
                pages_fetched += 1

                if pages_fetched >= max_pages:
                    logger.warning(
                        "nvd_max_pages_reached",
                        max_pages=max_pages,
                        total_results=total,
                        fetched=len(items),
                    )
                    break

                start_index += len(vulnerabilities)
                if start_index >= total:
                    break

        return items

    def _parse_cve(self, cve: dict[str, Any]) -> RawItem:
        cve_id = cve["id"]
        description = self._english_description(cve.get("descriptions", []))
        severity = self._extract_severity(cve.get("metrics", {}))
        published = cve.get("published", "")

        occurred_at = None
        if published:
            occurred_at = datetime.strptime(published, "%Y-%m-%dT%H:%M:%S.%f").replace(
                tzinfo=UTC
            )

        return RawItem(
            title=cve_id,
            url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
            summary=description,
            raw_data=cve,
            occurred_at=occurred_at,
            severity=severity,
            indicators=[{"type": "cve", "value": cve_id}],
        )

    @staticmethod
    def _english_description(descriptions: list[dict[str, Any]]) -> str:
        for desc in descriptions:
            if desc.get("lang") == "en":
                return str(desc["value"])
        return str(descriptions[0]["value"]) if descriptions else ""

    @staticmethod
    def _extract_severity(metrics: dict[str, Any]) -> str | None:
        for metric_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            metric_list = metrics.get(metric_key, [])
            if metric_list:
                cvss_data = metric_list[0].get("cvssData", {})
                severity: str | None = cvss_data.get("baseSeverity")
                return severity
        return None

    def dedupe_key(self, item: RawItem) -> str:
        return f"nvd:{item.raw_data['id']}"
