"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

import osint_core.metrics as metrics  # noqa: F401 — register custom Prometheus metrics
from osint_core.api.errors import ProblemError, problem_exception_handler
from osint_core.api.middleware.rate_limit import RateLimitMiddleware
from osint_core.api.routes import (
    alerts,
    audit,
    briefs,
    dashboard,
    entities,
    events,
    health,
    indicators,
    jobs,
    leads,
    me,
    plan,
    preferences,
    search,
    stream,
    watches,
)
from osint_core.config import settings
from osint_core.logging import configure_logging
from osint_core.tracing import init_fastapi_tracing

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown lifecycle."""
    configure_logging()
    logger.info("osint-core starting", version="0.1.0")
    yield
    # Close Redis connections held by middleware.
    for route in getattr(app, "middleware", []):
        mw = getattr(route, "cls", None)
        if mw is RateLimitMiddleware:
            # Walk the built middleware stack to find the instance.
            obj = app.middleware_stack
            while obj is not None:
                if isinstance(obj, RateLimitMiddleware):
                    await obj.close()
                    break
                obj = getattr(obj, "app", None)
    logger.info("osint-core shutting down")


app = FastAPI(
    title="OSINT Core",
    description="OSINT monitoring platform API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
)

init_fastapi_tracing(app)

app.add_exception_handler(ProblemError, problem_exception_handler)  # type: ignore[arg-type]
app.add_middleware(RateLimitMiddleware)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(dashboard.router)
app.include_router(plan.router)
app.include_router(events.router)
app.include_router(indicators.router)
app.include_router(entities.router)
app.include_router(alerts.router)
app.include_router(briefs.router)
app.include_router(search.router)
app.include_router(stream.router)
app.include_router(jobs.router)
app.include_router(audit.router)
app.include_router(watches.router)
app.include_router(leads.router)
app.include_router(preferences.router)
