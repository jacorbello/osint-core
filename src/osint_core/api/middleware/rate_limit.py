"""Redis-backed fixed-window rate limiting middleware."""

from __future__ import annotations

import time

import redis.asyncio as aioredis
import redis.exceptions
import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

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
    """Extract client IP, respecting X-Forwarded-For behind a trusted proxy.

    Note: This assumes deployment behind a trusted reverse proxy that sets
    X-Forwarded-For. If exposed directly to the internet, clients can spoof
    this header. Configure ``trust_proxy`` in settings to control this.
    """
    if settings.rate_limit_trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def _get_user_id(request: Request) -> str | None:
    """Return authenticated user id if present in request state."""
    return getattr(request.state, "user_sub", None)


async def _check_rate_limit(
    r: aioredis.Redis,
    key: str,
    limit: int,
) -> tuple[bool, int, int]:
    """Fixed-window counter using Redis INCR + EXPIRE.

    Returns (allowed, remaining, retry_after_seconds).
    """
    now = int(time.time())
    window_key = f"rl:{key}:{now // _WINDOW_SECONDS}"

    pipe = r.pipeline()
    pipe.incr(window_key)
    pipe.expire(window_key, _WINDOW_SECONDS)
    results: list[int] = await pipe.execute()
    count = results[0]

    remaining = max(0, limit - count)
    if count > limit:
        seconds_into_window = now % _WINDOW_SECONDS
        retry_after = _WINDOW_SECONDS - seconds_into_window
        return False, 0, retry_after

    return True, remaining, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP and per-user rate limiting backed by Redis."""

    def __init__(self, app: ASGIApp, redis_url: str | None = None) -> None:
        super().__init__(app)
        self._redis_url = redis_url or settings.redis_url
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                self._redis_url,
                socket_connect_timeout=2,
            )
        return self._redis

    async def close(self) -> None:
        """Close the Redis connection if open."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip exempt endpoints
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        ip = _get_client_ip(request)
        ip_limit = settings.rate_limit_per_ip
        user_limit = settings.rate_limit_per_user

        ip_remaining: int | None = None
        user_remaining: int | None = None

        try:
            r = await self._get_redis()

            # Check IP-based limit
            allowed, ip_remaining, retry_after = await _check_rate_limit(
                r, f"ip:{ip}", ip_limit
            )
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
                allowed, user_remaining, retry_after = await _check_rate_limit(
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

        except (redis.exceptions.RedisError, ConnectionError, OSError):
            # If Redis is unavailable, allow the request through (fail open).
            logger.warning("rate_limit_redis_unavailable", exc_info=True)
            return await call_next(request)

        response = await call_next(request)

        # Expose remaining budget in response headers.
        if ip_remaining is not None:
            remaining = ip_remaining
            if user_remaining is not None:
                remaining = min(remaining, user_remaining)
            response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response
