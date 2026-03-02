"""Search API routes — full-text and semantic search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.event import Event
from osint_core.schemas.event import EventList

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("", response_model=EventList)
async def search_events(
    q: str = Query(description="Search query string"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventList:
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

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total > 0 else 0

    return EventList(items=items, total=total, page=page, page_size=limit, pages=pages)


@router.get("/semantic", response_model=EventList)
async def search_semantic(
    q: str = Query(description="Natural language query for semantic search"),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserInfo = Depends(get_current_user),
) -> EventList:
    """Semantic similarity search via Qdrant.

    Note: This endpoint requires a running Qdrant instance and
    the vectorize service to have indexed events. Returns an empty
    list when Qdrant is unavailable.
    """
    # Qdrant integration is handled externally — return empty for now
    return EventList(items=[], total=0, page=1, page_size=limit, pages=0)
