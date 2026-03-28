"""CourtListener citation verification client."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx
import structlog

from osint_core.config import settings

logger = structlog.get_logger()

_BASE_URL = "https://www.courtlistener.com"
_CITATION_LOOKUP_PATH = "/api/rest/v4/citation-lookup/"
_MAX_TEXT_LENGTH = 64_000
_RATE_LIMIT_PER_MINUTE = 60
_DEFAULT_TIMEOUT = 30.0


@dataclass
class VerifiedCitation:
    """A citation that has been checked against CourtListener."""

    case_name: str
    citation: str
    courtlistener_url: str
    verified: bool
    relevance: str = ""


@dataclass
class _RateLimiter:
    """Simple sliding-window rate limiter."""

    max_per_minute: int = _RATE_LIMIT_PER_MINUTE
    _timestamps: list[float] = field(default_factory=list)

    def acquire(self) -> float:
        """Return 0 if allowed, or seconds to wait before next request."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        if len(self._timestamps) >= self.max_per_minute:
            wait = self._timestamps[0] - cutoff
            return max(0.0, wait)
        self._timestamps.append(now)
        return 0.0


class CourtListenerClient:
    """Async client for CourtListener's Citation Lookup API."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.courtlistener_api_key
        self._rate_limiter = _RateLimiter()

    async def verify_citations(self, text: str) -> list[VerifiedCitation]:
        """Extract and verify legal citations in *text* via CourtListener.

        Returns a list of :class:`VerifiedCitation` objects.  Unverifiable
        citations are returned with ``verified=False``.
        """
        if not text or not text.strip():
            return []

        truncated = text[:_MAX_TEXT_LENGTH]

        wait = self._rate_limiter.acquire()
        if wait > 0:
            logger.warning(
                "courtlistener_rate_limited", wait_seconds=round(wait, 1),
            )
            import asyncio
            await asyncio.sleep(wait)
            self._rate_limiter.acquire()

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    f"{_BASE_URL}{_CITATION_LOOKUP_PATH}",
                    data={"text": truncated},
                    headers=headers,
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("courtlistener_timeout", text_len=len(truncated))
            return [VerifiedCitation(
                case_name="",
                citation=truncated[:100],
                courtlistener_url="",
                verified=False,
                relevance="verification timed out",
            )]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "courtlistener_http_error",
                status=exc.response.status_code,
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning("courtlistener_error", error=str(exc))
            return []

        return _parse_response(resp.json())


def _parse_response(data: list | dict) -> list[VerifiedCitation]:
    """Parse the CourtListener citation-lookup response into VerifiedCitation objects."""
    citations: list[VerifiedCitation] = []

    # The API returns a list of citation match groups
    if isinstance(data, dict):
        data = [data]

    for item in data:
        if not isinstance(item, dict):
            continue

        case_name = item.get("case_name") or item.get("caseName") or ""
        citation_str = item.get("citation") or ""
        cl_url = item.get("absolute_url") or ""
        if cl_url and not cl_url.startswith("http"):
            cl_url = f"{_BASE_URL}{cl_url}"

        # A citation is verified if we got a non-empty absolute_url
        verified = bool(cl_url)

        citations.append(VerifiedCitation(
            case_name=str(case_name),
            citation=str(citation_str),
            courtlistener_url=cl_url,
            verified=verified,
            relevance="matched" if verified else "not independently verified",
        ))

    return citations
