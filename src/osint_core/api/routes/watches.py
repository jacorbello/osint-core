"""Watch API routes -- CRUD for regional and event-driven watches."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.watch import Watch
from osint_core.schemas.watch import (
    WatchCreateRequest,
    WatchList,
    WatchResponse,
    WatchStatusEnum,
    WatchUpdateRequest,
)

router = APIRouter(prefix="/api/v1/watches", tags=["watches"])


@router.post("", response_model=WatchResponse, status_code=201)
async def create_watch(
    body: WatchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Create a new dynamic watch."""
    expires_at = None
    if body.ttl_hours:
        expires_at = datetime.now(UTC) + timedelta(hours=body.ttl_hours)

    watch = Watch(
        name=body.name,
        watch_type="dynamic",
        status="active",
        region=body.region,
        country_codes=body.country_codes,
        bounding_box=body.bounding_box,
        keywords=body.keywords,
        source_filter=body.source_filter,
        severity_threshold=body.severity_threshold,
        plan_id=body.plan_id,
        ttl_hours=body.ttl_hours,
        expires_at=expires_at,
        created_by=current_user.username,
    )

    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return watch


@router.get("", response_model=WatchList)
async def list_watches(
    status: WatchStatusEnum | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> WatchList:
    """List watches with optional status filter."""
    stmt = select(Watch)
    count_stmt = select(func.count()).select_from(Watch)

    if status:
        stmt = stmt.where(Watch.status == status)
        count_stmt = count_stmt.where(Watch.status == status)

    stmt = stmt.order_by(Watch.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total > 0 else 0

    return WatchList(items=items, total=total, page=page, page_size=limit, pages=pages)


@router.get("/{watch_id}", response_model=WatchResponse)
async def get_watch(
    watch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Get a single watch by ID."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    return watch


@router.patch("/{watch_id}", response_model=WatchResponse)
async def update_watch(
    watch_id: uuid.UUID,
    body: WatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Update a watch (pause, adjust filters, etc.)."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(watch, field, value)

    await db.commit()
    await db.refresh(watch)
    return watch


@router.post("/{watch_id}/promote", response_model=WatchResponse)
async def promote_watch(
    watch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Promote a dynamic watch to persistent."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    if watch.watch_type != "dynamic":
        raise HTTPException(status_code=400, detail="Only dynamic watches can be promoted")

    watch.status = "promoted"
    watch.watch_type = "persistent"
    watch.promoted_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(watch)
    return watch


@router.delete("/{watch_id}", status_code=204)
async def delete_watch(
    watch_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> None:
    """Expire/delete a watch."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(status_code=404, detail="Watch not found")
    watch.status = "expired"
    await db.commit()
