"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from osint_core.api.routes import health
from osint_core.config import settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown lifecycle."""
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
