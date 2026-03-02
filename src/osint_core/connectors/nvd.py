"""NVD API 2.0 feed connector."""

from datetime import UTC, datetime

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class NvdConnector(BaseConnector):
    """Fetches recent CVEs from the NVD API 2.0 with pagination support."""

    RESULTS_PER_PAGE = 2000

    async def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        start_index = 0

        async with httpx.AsyncClient() as client:
            while True:
                params = {"startIndex": start_index, "resultsPerPage": self.RESULTS_PER_PAGE}
                params.update(self.config.extra)

                resp = await client.get(self.config.url, params=params)
                resp.raise_for_status()
                data = resp.json()

                for entry in data.get("vulnerabilities", []):
                    cve = entry["cve"]
                    items.append(self._parse_cve(cve))

                total = data.get("totalResults", 0)
                start_index += len(data.get("vulnerabilities", []))
                if start_index >= total:
                    break

        return items

    def _parse_cve(self, cve: dict) -> RawItem:
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
    def _english_description(descriptions: list[dict]) -> str:
        for desc in descriptions:
            if desc.get("lang") == "en":
                return desc["value"]
        return descriptions[0]["value"] if descriptions else ""

    @staticmethod
    def _extract_severity(metrics: dict) -> str | None:
        for metric_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            metric_list = metrics.get(metric_key, [])
            if metric_list:
                cvss_data = metric_list[0].get("cvssData", {})
                return cvss_data.get("baseSeverity")
        return None

    def dedupe_key(self, item: RawItem) -> str:
        return f"nvd:{item.raw_data['id']}"
