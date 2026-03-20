"""Redis-backed sliding window rate limiting middleware."""

from __future__ import annotations

import time

import redis.asyncio as aioredis
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from osint_core.config import settings

logger = structlog.get_logger()

# Paths exempt from rate limiting (health, readiness, metrics).
_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/metrics",
        "/api/v1/system/health",
        "/api/v1/system/readiness",
    }
)

_WINDOW_SECONDS = 60


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _get_user_id(request: Request) -> str | None:
    """Return authenticated user id if present in request state."""
    return getattr(request.state, "user_sub", None)  # type: ignore[return-value]


async def _check_rate_limit(
    redis: aioredis.Redis,  # type: ignore[type-arg]
    key: str,
    limit: int,
) -> tuple[bool, int, int]:
    """Sliding window counter using Redis INCR + EXPIRE.

    Returns (allowed, remaining, retry_after_seconds).
    """
    now = int(time.time())
    window_key = f"rl:{key}:{now // _WINDOW_SECONDS}"

    pipe = redis.pipeline()
    pipe.incr(window_key)
    pipe.expire(window_key, _WINDOW_SECONDS)
    results: list[int] = await pipe.execute()  # type: ignore[assignment]
    count = results[0]

    remaining = max(0, limit - count)
    if count > limit:
        seconds_into_window = now % _WINDOW_SECONDS
        retry_after = _WINDOW_SECONDS - seconds_into_window
        return False, 0, retry_after

    return True, remaining, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP and per-user rate limiting backed by Redis."""

    def __init__(self, app: Request, redis_url: str | None = None) -> None:  # type: ignore[override]
        super().__init__(app)
        self._redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def _get_redis(self) -> aioredis.Redis:  # type: ignore[type-arg]
        if self._redis is None:
            self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._redis_url,
                socket_connect_timeout=2,
            )
        return self._redis

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip exempt endpoints
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        ip = _get_client_ip(request)
        ip_limit = settings.rate_limit_per_ip
        user_limit = settings.rate_limit_per_user

        try:
            r = await self._get_redis()

            # Check IP-based limit
            allowed, remaining, retry_after = await _check_rate_limit(r, f"ip:{ip}", ip_limit)
            if not allowed:
                logger.warning("rate_limit_exceeded", key=f"ip:{ip}", limit=ip_limit)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"},
                    headers={"Retry-After": str(retry_after)},
                )

            # Check user-based limit (if authenticated)
            user_id = _get_user_id(request)
            if user_id:
                allowed, remaining, retry_after = await _check_rate_limit(
                    r, f"user:{user_id}", user_limit
                )
                if not allowed:
                    logger.warning(
                        "rate_limit_exceeded", key=f"user:{user_id}", limit=user_limit
                    )
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too Many Requests"},
                        headers={"Retry-After": str(retry_after)},
                    )

        except Exception:
            # If Redis is unavailable, allow the request through (fail open).
            logger.warning("rate_limit_redis_unavailable", exc_info=True)

        return await call_next(request)
