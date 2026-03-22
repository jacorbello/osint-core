"""ACLED conflict event data connector — OAuth-based auth."""
from __future__ import annotations

import contextlib
import hashlib
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from .base import BaseConnector, RawItem

logger = structlog.get_logger()

_TOKEN_URL = "https://acleddata.com/oauth/token"
_DEFAULT_API_URL = "https://acleddata.com/api/acled/read"

# Module-level token cache shared across connector instances.
_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}


async def _get_access_token(email: str, password: str) -> str:
    """Return a cached Bearer token, refreshing via OAuth if expired."""
    if _token_cache["access_token"] and time.monotonic() < _token_cache["expires_at"]:
        return str(_token_cache["access_token"])

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={"email": email, "password": password},
        )
        resp.raise_for_status()
    body = resp.json()
    _token_cache["access_token"] = body["access_token"]
    # Cache with a 60-second safety margin.
    expires_in = int(body.get("expires_in", 86400))
    _token_cache["expires_at"] = time.monotonic() + expires_in - 60
    logger.info("acled_token_refreshed", expires_in=expires_in)
    return str(_token_cache["access_token"])


class AcledConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        email = self.config.extra.get("email", "")
        password = self.config.extra.get("password", "")
        token = await _get_access_token(email, password)

        params: dict[str, str] = {
            "limit": str(self.config.extra.get("max_items", 100)),
        }
        country = self.config.extra.get("country")
        if country:
            params["country"] = country

        url = self.config.url or _DEFAULT_API_URL
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        events = resp.json().get("data", [])
        return [self._parse(e) for e in events if e.get("notes")]

    def _parse(self, event: dict[str, Any]) -> RawItem:
        date_str = event.get("event_date", "")
        occurred_at = None
        if date_str:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        lat = event.get("latitude")
        lon = event.get("longitude")
        fatalities_raw = event.get("fatalities", "0")
        return RawItem(
            title=f"{event.get('event_type', '')}: {event.get('notes', '')[:100]}",
            url=(
                "https://acleddata.com/data-export-tool/"
                f"?event_id={event.get('event_id_cnty', '')}"
            ),
            raw_data=event,
            summary=event.get("notes", ""),
            occurred_at=occurred_at,
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
            country_code=event.get("iso3"),
            source_category="geopolitical",
            event_type=event.get("event_type"),
            fatalities=int(fatalities_raw) if fatalities_raw else 0,
            actors=(
                [{"name": event.get("actor1", ""), "role": "primary"}]
                if event.get("actor1")
                else []
            ),
        )

    def dedupe_key(self, item: RawItem) -> str:
        eid = item.raw_data.get("event_id_cnty", item.url)
        return f"acled:{hashlib.sha256(eid.encode()).hexdigest()[:16]}"
