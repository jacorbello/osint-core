"""CISA Known Exploited Vulnerabilities (KEV) feed connector."""

from datetime import UTC, datetime

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class CisaKevConnector(BaseConnector):
    """Fetches the CISA KEV catalog and returns each vulnerability as a RawItem."""

    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(self.config.url)
            resp.raise_for_status()

        data = resp.json()
        items: list[RawItem] = []

        for vuln in data.get("vulnerabilities", []):
            cve_id = vuln["cveID"]
            vendor = vuln.get("vendorProject", "")
            product = vuln.get("product", "")
            description = vuln.get("shortDescription", "")
            date_added = vuln.get("dateAdded", "")

            occurred_at = None
            if date_added:
                occurred_at = datetime.strptime(date_added, "%Y-%m-%d").replace(
                    tzinfo=UTC
                )

            items.append(
                RawItem(
                    title=f"{cve_id} - {vendor} {product}",
                    url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                    summary=description,
                    raw_data=vuln,
                    occurred_at=occurred_at,
                    indicators=[{"type": "cve", "value": cve_id}],
                )
            )

        return items

    def dedupe_key(self, item: RawItem) -> str:
        return f"cisa_kev:{item.raw_data['cveID']}"
