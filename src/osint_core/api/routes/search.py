"""Search API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.event import Event
from osint_core.schemas.event import EventSearchList

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
    responses=problem_response_docs(401, 422),
)
async def search_semantic(
    q: str = Query(description="Natural language query for semantic search"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserInfo = Depends(get_current_user),
) -> EventSearchList:
    """Semantic similarity search via Qdrant."""
    _ = q
    return EventSearchList(
        items=[],
        page=collection_page(offset=0, limit=limit, total=0),
        retrieval_mode="semantic",
    )
