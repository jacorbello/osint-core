"""Indicator API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.indicator import Indicator
from osint_core.schemas.indicator import IndicatorList, IndicatorResponse

router = APIRouter(prefix="/api/v1/indicators", tags=["indicators"])


@router.get(
    "",
    response_model=IndicatorList,
    operation_id="listIndicators",
    responses=problem_response_docs(401, 422),
)
async def list_indicators(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    indicator_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> IndicatorList:
    """List indicators with optional type filter."""
    stmt = select(Indicator)
    count_stmt = select(func.count()).select_from(Indicator)

    if indicator_type is not None:
        stmt = stmt.where(Indicator.indicator_type == indicator_type)
        count_stmt = count_stmt.where(Indicator.indicator_type == indicator_type)

    stmt = stmt.order_by(Indicator.last_seen.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return IndicatorList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


@router.get(
    "/{indicator_id}",
    response_model=IndicatorResponse,
    operation_id="getIndicator",
    responses=problem_response_docs(401, 404, 422),
)
async def get_indicator(
    indicator_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> IndicatorResponse:
    """Get a single indicator by ID."""
    result = await db.execute(select(Indicator).where(Indicator.id == indicator_id))
    indicator = result.scalar_one_or_none()
    if indicator is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Indicator not found",
        )  # type: ignore[return-value]
    return indicator  # type: ignore[return-value]
