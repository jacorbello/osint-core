"""Watch API routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
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


@router.post(
    "",
    response_model=WatchResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createWatch",
    responses=problem_response_docs(401, 409, 422),
)
async def create_watch(
    body: WatchCreateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Create a new watch."""
    expires_at = None
    if body.ttl_hours:
        expires_at = datetime.now(UTC) + timedelta(hours=body.ttl_hours)

    watch = Watch(
        name=body.name,
        watch_type="dynamic",
        status="active",
        region=body.region,
        country_codes=body.country_codes,
        bounding_box=body.bounding_box.model_dump() if body.bounding_box else None,
        keywords=body.keywords,
        source_filter=body.source_filter,
        severity_threshold=body.severity_threshold,
        plan_id=body.plan_id,
        ttl_hours=body.ttl_hours,
        expires_at=expires_at,
        created_by=current_user.username,
    )

    db.add(watch)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return problem_response(
            request,
            status_code=409,
            code="conflict",
            detail="A watch with this name already exists",
        )  # type: ignore[return-value]

    await db.refresh(watch)
    response.headers["Location"] = f"/api/v1/watches/{watch.id}"
    return watch


@router.get(
    "",
    response_model=WatchList,
    operation_id="listWatches",
    responses=problem_response_docs(401, 422),
)
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

    return WatchList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


@router.get(
    "/{watch_id}",
    response_model=WatchResponse,
    operation_id="getWatch",
    responses=problem_response_docs(401, 404, 422),
)
async def get_watch(
    watch_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Get a single watch by ID."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Watch not found",
        )  # type: ignore[return-value]
    return watch


@router.patch(
    "/{watch_id}",
    response_model=WatchResponse,
    operation_id="updateWatch",
    responses=problem_response_docs(401, 404, 409, 422),
)
async def update_watch(
    watch_id: uuid.UUID,
    body: WatchUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Watch:
    """Update a watch."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Watch not found",
        )  # type: ignore[return-value]

    update_data = body.model_dump(exclude_unset=True)

    if update_data.get("watch_type") == "persistent" and watch.watch_type == "persistent":
        return problem_response(
            request,
            status_code=409,
            code="invalid_state_transition",
            detail="Watch is already persistent",
        )  # type: ignore[return-value]

    for field, value in update_data.items():
        setattr(watch, field, value)

    if "ttl_hours" in update_data:
        if watch.ttl_hours and watch.ttl_hours > 0:
            watch.expires_at = datetime.now(UTC) + timedelta(hours=watch.ttl_hours)
        else:
            watch.expires_at = None
    elif watch.ttl_hours:
        watch.expires_at = datetime.now(UTC) + timedelta(hours=watch.ttl_hours)

    await db.commit()
    await db.refresh(watch)
    return watch


@router.delete(
    "/{watch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteWatch",
    responses=problem_response_docs(401, 404, 422),
)
async def delete_watch(
    watch_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> None:
    """Delete a watch."""
    result = await db.execute(select(Watch).where(Watch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Watch not found",
        )  # type: ignore[return-value]

    await db.delete(watch)
    await db.commit()
