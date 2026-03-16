"""Event API routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.event import Event
from osint_core.schemas.event import EventList, EventResponse

router = APIRouter(prefix="/api/v1/events", tags=["events"])

_SORT_FIELDS = {
    "ingested_at": Event.ingested_at,
    "occurred_at": Event.occurred_at,
    "score": Event.score,
}


def _parse_sort(sort: str | None):
    """Parse a sort parameter like '-score' or 'ingested_at' into an ORDER BY clause."""
    if sort is None:
        return Event.ingested_at.desc()

    descending = sort.startswith("-")
    field_name = sort.lstrip("-")
    column = _SORT_FIELDS.get(field_name)
    if column is None:
        # Unknown sort field — fall back to default
        return Event.ingested_at.desc()

    return column.desc().nullslast() if descending else column.asc().nullsfirst()


@router.get("", response_model=EventList)
async def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    sort: str | None = Query(
        default=None,
        description="Sort field. Prefix with '-' for descending. "
                    "Supported: ingested_at, occurred_at, score. "
                    "Example: -score returns highest scores first.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventList:
    """List events with optional filters."""
    stmt = select(Event)
    count_stmt = select(func.count()).select_from(Event)

    if source_id is not None:
        stmt = stmt.where(Event.source_id == source_id)
        count_stmt = count_stmt.where(Event.source_id == source_id)
    if severity is not None:
        stmt = stmt.where(Event.severity == severity)
        count_stmt = count_stmt.where(Event.severity == severity)
    if date_from is not None:
        stmt = stmt.where(Event.ingested_at >= date_from)
        count_stmt = count_stmt.where(Event.ingested_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Event.ingested_at <= date_to)
        count_stmt = count_stmt.where(Event.ingested_at <= date_to)

    stmt = stmt.order_by(_parse_sort(sort)).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total > 0 else 0

    return EventList(items=items, total=total, page=page, page_size=limit, pages=pages)


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventResponse:
    """Get a single event by ID."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event  # type: ignore[return-value]
