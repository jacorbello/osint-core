"""Health check endpoints."""

import structlog
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from osint_core.config import settings
from osint_core.db import async_session

logger = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/healthz", operation_id="legacyHealth")
@router.get("/api/v1/system/health", operation_id="systemHealth")
async def healthz() -> dict[str, str]:
    """Liveness probe -- always returns 200 if the process is running."""
    return {"status": "ok"}


@router.get("/readyz", operation_id="legacyReadiness")
@router.get("/api/v1/system/readiness", operation_id="systemReadiness")
async def readyz(response: Response) -> dict[str, str]:
    """Readiness probe -- checks postgres, redis, and qdrant connectivity."""
    checks: dict[str, str] = {}

    # --- Postgres ---
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        logger.warning("readyz: postgres check failed", exc_info=True)
        checks["postgres"] = "error"

    # --- Redis ---
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)  # type: ignore[no-untyped-call]
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        logger.warning("readyz: redis check failed", exc_info=True)
        checks["redis"] = "error"

    # --- Qdrant ---
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(
                f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz"
            )
            checks["qdrant"] = "ok" if resp.status_code == 200 else "error"
    except Exception:
        logger.warning("readyz: qdrant check failed", exc_info=True)
        checks["qdrant"] = "error"

    if any(v == "error" for v in checks.values()):
        response.status_code = 503

    return checks


@router.get("/metrics", operation_id="metrics")
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics without middleware instrumentation."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
