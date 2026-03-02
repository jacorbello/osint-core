"""OSV API feed connector."""

from datetime import UTC, datetime

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class OsvConnector(BaseConnector):
    """Fetches vulnerabilities from the OSV API by ecosystem."""

    async def fetch(self) -> list[RawItem]:
        ecosystem = self.config.extra.get("ecosystem", "")
        body: dict = {"package": {"ecosystem": ecosystem}}

        async with httpx.AsyncClient() as client:
            resp = await client.post(self.config.url, json=body)
            resp.raise_for_status()

        data = resp.json()
        items: list[RawItem] = []

        for vuln in data.get("vulns", []):
            items.append(self._parse_vuln(vuln))

        return items

    def _parse_vuln(self, vuln: dict) -> RawItem:
        vuln_id = vuln["id"]
        summary = vuln.get("summary", "")
        published = vuln.get("published", "")

        occurred_at = None
        if published:
            occurred_at = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(
                UTC
            )

        indicators = self._build_indicators(vuln)

        return RawItem(
            title=vuln_id,
            url=f"https://osv.dev/vulnerability/{vuln_id}",
            summary=summary,
            raw_data=vuln,
            occurred_at=occurred_at,
            indicators=indicators,
        )

    @staticmethod
    def _build_indicators(vuln: dict) -> list[dict]:
        indicators: list[dict] = []

        # Add CVE aliases as indicators
        for alias in vuln.get("aliases", []):
            if alias.startswith("CVE-"):
                indicators.append({"type": "cve", "value": alias})

        # Add affected package names as indicators
        for affected in vuln.get("affected", []):
            pkg = affected.get("package", {})
            name = pkg.get("name", "")
            if name:
                indicators.append({
                    "type": "package",
                    "value": name,
                    "ecosystem": pkg.get("ecosystem", ""),
                })

        return indicators

    def dedupe_key(self, item: RawItem) -> str:
        return f"osv:{item.raw_data['id']}"
