"""ACLED conflict event data connector — OAuth-based auth."""
from __future__ import annotations

import asyncio
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

# Module-level token cache keyed by email so different accounts stay isolated.
_token_cache: dict[str, dict[str, Any]] = {}


async def _get_access_token(email: str, password: str) -> str:
    """Return a cached Bearer token, refreshing via OAuth if expired."""
    if not email or not password:
        raise ValueError("ACLED email and password must be non-empty")

    entry = _token_cache.get(email)
    if entry and entry["access_token"] and time.monotonic() < entry["expires_at"]:
        return str(entry["access_token"])

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "username": email,
                "password": password,
            },
        )
        if resp.status_code in (401, 403):
            logger.error(
                "acled_auth_failed",
                status=resp.status_code,
                email=email,
                body_preview=resp.text[:200],
            )
            raise RuntimeError(
                f"ACLED authentication failed (HTTP {resp.status_code}): "
                "check OSINT_ACLED_EMAIL and OSINT_ACLED_PASSWORD"
            )
        resp.raise_for_status()
    body = resp.json()
    expires_in = int(body.get("expires_in", 86400))
    # Clamp safety margin so short-lived tokens don't expire immediately.
    margin = min(60, int(expires_in * 0.1))
    _token_cache[email] = {
        "access_token": body["access_token"],
        "expires_at": time.monotonic() + expires_in - margin,
    }
    logger.info("acled_token_refreshed", expires_in=expires_in, email=email)
    return str(_token_cache[email]["access_token"])


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
            for attempt in range(3):
                resp = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code in (429, 503):
                    try:
                        retry_after = min(
                            int(resp.headers.get("Retry-After", "10")), 60,
                        )
                    except (ValueError, TypeError):
                        retry_after = 10
                    logger.warning(
                        "acled_rate_limited",
                        status=resp.status_code,
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    if attempt < 2:
                        await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                break
            else:
                logger.error("acled_max_retries_exceeded", attempts=3)
                return []

        payload = resp.json()
        if not payload.get("success", True):
            logger.error(
                "acled_api_error",
                status=payload.get("status"),
                messages=payload.get("messages"),
            )
            return []

        events = payload.get("data", [])
        if not events:
            logger.warning(
                "acled_no_events",
                country=country,
                url=url,
                params=params,
            )
        return [self._parse(e) for e in events]

    def _parse(self, event: dict[str, Any]) -> RawItem:
        date_str = event.get("event_date", "")
        occurred_at = None
        if date_str:
            with contextlib.suppress(ValueError):
                occurred_at = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        lat = event.get("latitude")
        lon = event.get("longitude")
        fatalities_raw = event.get("fatalities", "0")
        notes = event.get("notes", "")
        event_type = event.get("event_type", "")
        title = f"{event_type}: {notes[:100]}" if notes else event_type
        return RawItem(
            title=title,
            url=(
                "https://acleddata.com/data-export-tool/"
                f"?event_id={event.get('event_id_cnty', '')}"
            ),
            raw_data=event,
            summary=notes,
            occurred_at=occurred_at,
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
            country_code=event.get("iso3"),
            source_category="geopolitical",
            event_type=event_type,
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
