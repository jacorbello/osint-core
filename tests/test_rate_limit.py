"""Tests for the rate limiting middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from osint_core.api.middleware.rate_limit import (
    _EXEMPT_PATHS,
    RateLimitMiddleware,
    _check_rate_limit,
    _get_client_ip,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(redis_mock: AsyncMock | None = None) -> FastAPI:
    """Build a minimal FastAPI app with rate limiting middleware."""
    test_app = FastAPI()

    @test_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse("# metrics")

    @test_app.get("/api/v1/system/health")
    async def system_health() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/api/v1/system/readiness")
    async def system_readiness() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/api/v1/events")
    async def events() -> dict[str, str]:
        return {"data": "events"}

    test_app.add_middleware(RateLimitMiddleware)

    if redis_mock is not None:
        # Inject mock redis into middleware instances
        for mw in test_app.middleware_stack.__dict__.get("app", test_app).__dict__.values():
            if isinstance(mw, RateLimitMiddleware):
                mw._redis = redis_mock

    return test_app


def _make_redis_mock(counts: list[int] | None = None) -> AsyncMock:
    """Create a mock Redis client that returns specified counts from pipeline."""
    mock_redis = AsyncMock()
    mock_pipe = AsyncMock()

    if counts is None:
        counts = [1]

    # Each call to pipe.execute() returns [count, True]
    mock_pipe.execute = AsyncMock(side_effect=[[c, True] for c in counts])
    mock_pipe.incr = MagicMock(return_value=mock_pipe)
    mock_pipe.expire = MagicMock(return_value=mock_pipe)
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    return mock_redis


# ---------------------------------------------------------------------------
# Unit: _get_client_ip
# ---------------------------------------------------------------------------


class TestGetClientIp:
    def test_direct_connection(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"
        assert _get_client_ip(request) == "192.168.1.1"

    def test_x_forwarded_for_single(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-forwarded-for": "10.0.0.1"}
        assert _get_client_ip(request) == "10.0.0.1"

    def test_x_forwarded_for_multiple(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {"x-forwarded-for": "10.0.0.1, 10.0.0.2, 10.0.0.3"}
        assert _get_client_ip(request) == "10.0.0.1"

    def test_no_client(self) -> None:
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None
        assert _get_client_ip(request) == "unknown"


# ---------------------------------------------------------------------------
# Unit: _check_rate_limit
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_under_limit_allowed(self) -> None:
        mock_redis = _make_redis_mock([5])
        allowed, remaining, retry_after = await _check_rate_limit(mock_redis, "ip:1.2.3.4", 100)
        assert allowed is True
        assert remaining == 95
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_at_limit_allowed(self) -> None:
        mock_redis = _make_redis_mock([100])
        allowed, remaining, retry_after = await _check_rate_limit(mock_redis, "ip:1.2.3.4", 100)
        assert allowed is True
        assert remaining == 0
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_over_limit_rejected(self) -> None:
        mock_redis = _make_redis_mock([101])
        allowed, remaining, retry_after = await _check_rate_limit(mock_redis, "ip:1.2.3.4", 100)
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0


# ---------------------------------------------------------------------------
# Unit: Exempt endpoints
# ---------------------------------------------------------------------------


class TestExemptPaths:
    def test_exempt_paths_defined(self) -> None:
        assert "/healthz" in _EXEMPT_PATHS
        assert "/readyz" in _EXEMPT_PATHS
        assert "/metrics" in _EXEMPT_PATHS
        assert "/api/v1/system/health" in _EXEMPT_PATHS
        assert "/api/v1/system/readiness" in _EXEMPT_PATHS

    def test_healthz_exempt(self) -> None:
        """Health endpoint should pass through even when Redis is down."""
        with patch(
            "osint_core.api.middleware.rate_limit.aioredis.from_url",
            side_effect=ConnectionError("no redis"),
        ):
            app = _build_app()
            client = TestClient(app)
            resp = client.get("/healthz")
            assert resp.status_code == 200

    def test_readyz_exempt(self) -> None:
        with patch(
            "osint_core.api.middleware.rate_limit.aioredis.from_url",
            side_effect=ConnectionError("no redis"),
        ):
            app = _build_app()
            client = TestClient(app)
            resp = client.get("/readyz")
            assert resp.status_code == 200

    def test_metrics_exempt(self) -> None:
        with patch(
            "osint_core.api.middleware.rate_limit.aioredis.from_url",
            side_effect=ConnectionError("no redis"),
        ):
            app = _build_app()
            client = TestClient(app)
            resp = client.get("/metrics")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Integration: 429 response
# ---------------------------------------------------------------------------


class TestRateLimitResponse:
    def test_returns_429_when_limit_exceeded(self) -> None:
        """Requests exceeding the IP limit should get 429 with Retry-After."""
        mock_redis = _make_redis_mock()
        # Override execute to always return over-limit count
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[101, True])
        mock_pipe.incr = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        app = _build_app()
        # Inject redis mock into middleware
        # Walk the middleware stack to find our middleware
        _inject_redis(app, mock_redis)

        with patch("osint_core.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_per_ip = 100
            mock_settings.rate_limit_per_user = 300
            mock_settings.redis_url = "redis://localhost:6379/0"

            client = TestClient(app)
            resp = client.get("/api/v1/events")
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            assert resp.json() == {"detail": "Too Many Requests"}

    def test_allows_request_under_limit(self) -> None:
        """Requests under the limit should pass through."""
        mock_redis = _make_redis_mock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True])
        mock_pipe.incr = MagicMock(return_value=mock_pipe)
        mock_pipe.expire = MagicMock(return_value=mock_pipe)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        app = _build_app()
        _inject_redis(app, mock_redis)

        with patch("osint_core.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_per_ip = 100
            mock_settings.rate_limit_per_user = 300
            mock_settings.redis_url = "redis://localhost:6379/0"

            client = TestClient(app)
            resp = client.get("/api/v1/events")
            assert resp.status_code == 200

    def test_fails_open_when_redis_unavailable(self) -> None:
        """When Redis is unreachable, requests should be allowed (fail open)."""
        with patch(
            "osint_core.api.middleware.rate_limit.aioredis.from_url",
            side_effect=ConnectionError("no redis"),
        ):
            app = _build_app()
            client = TestClient(app)
            resp = client.get("/api/v1/events")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestConfig:
    def test_default_rate_limits(self) -> None:
        from osint_core.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            redis_url="redis://localhost:6379/0",
        )
        assert s.rate_limit_per_ip == 100
        assert s.rate_limit_per_user == 300

    def test_custom_rate_limits(self) -> None:
        from osint_core.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test",
            redis_url="redis://localhost:6379/0",
            rate_limit_per_ip=50,
            rate_limit_per_user=150,
        )
        assert s.rate_limit_per_ip == 50
        assert s.rate_limit_per_user == 150


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inject_redis(app: FastAPI, mock_redis: AsyncMock) -> None:
    """Walk middleware stack and inject a mock Redis into RateLimitMiddleware."""
    obj = app.middleware_stack
    while obj is not None:
        if isinstance(obj, RateLimitMiddleware):
            obj._redis = mock_redis
            return
        obj = getattr(obj, "app", None)
