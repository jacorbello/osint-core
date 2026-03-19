"""Search API routes."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.event import Event
from osint_core.schemas.event import EventSearchList
from osint_core.services.vectorize import search_similar

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get(
    "/events",
    response_model=EventSearchList,
    operation_id="searchEvents",
    responses=problem_response_docs(401, 422),
)
async def search_events(
    q: str = Query(description="Search query string"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventSearchList:
    """Full-text search over events using Postgres tsvector."""
    ts_query = func.plainto_tsquery("english", q)
    stmt = (
        select(Event)
        .where(Event.search_vector.op("@@")(ts_query))
        .order_by(Event.ingested_at.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = (
        select(func.count())
        .select_from(Event)
        .where(Event.search_vector.op("@@")(ts_query))
    )

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return EventSearchList(
        items=items,
        page=collection_page(offset=offset, limit=limit, total=total),
        retrieval_mode="lexical",
    )


@router.get(
    "/events:semantic",
    response_model=EventSearchList,
    operation_id="searchEventsSemantic",
    responses=problem_response_docs(401, 422, 503),
)
async def search_semantic(
    q: str = Query(description="Natural language query for semantic search"),
    limit: int = Query(default=20, ge=1, le=100),
    score_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    request: Request = ...,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventSearchList:
    """Semantic similarity search via Qdrant."""
    try:
        hits = await asyncio.to_thread(
            search_similar, q, limit=limit, score_threshold=score_threshold,
        )
    except Exception:
        logger.exception("semantic_search_failed", query=q)
        return problem_response(  # type: ignore[return-value]
            request,
            status_code=503,
            code="dependency_unavailable",
            detail="Semantic search is temporarily unavailable",
        )

    if not hits:
        logger.debug("Semantic search for %r returned 0 Qdrant hits", q)
        return EventSearchList(
            items=[],
            page=collection_page(offset=0, limit=limit, total=0),
            retrieval_mode="semantic",
        )

    # Extract event UUIDs from Qdrant payloads (stored as strings)
    event_ids: list[uuid.UUID] = []
    for hit in hits:
        raw_id = hit.get("payload", {}).get("event_id")
        if raw_id:
            try:
                event_ids.append(uuid.UUID(str(raw_id)))
            except ValueError:
                logger.warning("Qdrant hit has non-UUID event_id: %r", raw_id)

    if not event_ids:
        return EventSearchList(
            items=[],
            page=collection_page(offset=0, limit=limit, total=0),
            retrieval_mode="semantic",
        )

    stmt = select(Event).where(Event.id.in_(event_ids))
    result = await db.execute(stmt)
    events_by_id = {str(e.id): e for e in result.scalars().all()}

    # Return events in Qdrant score order (highest similarity first)
    ordered = [events_by_id[str(eid)] for eid in event_ids if str(eid) in events_by_id]

    return EventSearchList(
        items=ordered,
        page=collection_page(offset=0, limit=limit, total=len(ordered)),
        retrieval_mode="semantic",
    )
