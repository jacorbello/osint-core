"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from osint_core.api.routes import (
    alerts,
    audit,
    briefs,
    entities,
    events,
    health,
    indicators,
    ingest,
    jobs,
    plan,
    search,
)
from osint_core.config import settings
from osint_core.logging import configure_logging
import osint_core.metrics as metrics  # noqa: F401 — register custom Prometheus metrics

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown lifecycle."""
    configure_logging()
    logger.info("osint-core starting", version="0.1.0")
    yield
    logger.info("osint-core shutting down")


app = FastAPI(
    title="OSINT Core",
    description="OSINT monitoring platform API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")

app.include_router(health.router)
app.include_router(plan.router)
app.include_router(events.router)
app.include_router(indicators.router)
app.include_router(entities.router)
app.include_router(alerts.router)
app.include_router(briefs.router)
app.include_router(search.router)
app.include_router(ingest.router)
app.include_router(jobs.router)
app.include_router(audit.router)
