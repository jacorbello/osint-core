"""Brief API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.config import settings
from osint_core.models.brief import Brief
from osint_core.schemas.brief import BriefGenerateRequest, BriefList, BriefResponse
from osint_core.services.brief_generator import BriefGenerator

router = APIRouter(prefix="/api/v1/briefs", tags=["briefs"])


@router.get("", response_model=BriefList)
async def list_briefs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BriefList:
    """List intelligence briefs."""
    stmt = select(Brief).order_by(Brief.created_at.desc()).limit(limit).offset(offset)
    count_stmt = select(func.count()).select_from(Brief)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total > 0 else 0

    return BriefList(items=items, total=total, page=page, page_size=limit, pages=pages)


@router.get("/{brief_id}", response_model=BriefResponse)
async def get_brief(
    brief_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BriefResponse:
    """Get a single brief by ID."""
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    return brief  # type: ignore[return-value]


@router.post("/generate", response_model=BriefResponse)
async def generate_brief(
    body: BriefGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BriefResponse:
    """Generate a new intelligence brief using the BriefGenerator."""
    generator = BriefGenerator(
        vllm_url=settings.vllm_url,
        llm_model=settings.llm_model,
    )

    content_md = await generator.generate(
        query=body.query,
        events=[],
        indicators=[],
        entities=[],
    )

    brief = Brief(
        title=body.query,
        content_md=content_md,
        target_query=body.query,
        generated_by="vllm",
        model_id=settings.llm_model,
        requested_by=current_user.username,
    )
    db.add(brief)
    await db.flush()
    await db.commit()
    return brief  # type: ignore[return-value]
