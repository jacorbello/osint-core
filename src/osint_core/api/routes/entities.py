"""Entity API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.entity import Entity
from osint_core.schemas.entity import EntityList, EntityResponse

router = APIRouter(prefix="/api/v1/entities", tags=["entities"])


@router.get(
    "",
    response_model=EntityList,
    operation_id="listEntities",
    responses=problem_response_docs(401, 422),
)
async def list_entities(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    entity_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EntityList:
    """List entities with optional type filter."""
    stmt = select(Entity)
    count_stmt = select(func.count()).select_from(Entity)

    if entity_type is not None:
        stmt = stmt.where(Entity.entity_type == entity_type)
        count_stmt = count_stmt.where(Entity.entity_type == entity_type)

    stmt = stmt.order_by(Entity.last_seen.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return EntityList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


@router.get(
    "/{entity_id}",
    response_model=EntityResponse,
    operation_id="getEntity",
    responses=problem_response_docs(401, 404, 422),
)
async def get_entity(
    entity_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EntityResponse:
    """Get a single entity by ID."""
    result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = result.scalar_one_or_none()
    if entity is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Entity not found",
        )  # type: ignore[return-value]
    return entity  # type: ignore[return-value]
