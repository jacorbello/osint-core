"""Brief API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.config import settings
from osint_core.models.brief import Brief
from osint_core.schemas.brief import BriefCreateRequest, BriefList, BriefResponse
from osint_core.services.brief_generator import BriefGenerator

router = APIRouter(prefix="/api/v1/briefs", tags=["briefs"])


@router.get(
    "",
    response_model=BriefList,
    operation_id="listBriefs",
    responses=problem_response_docs(401, 422),
)
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

    return BriefList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


@router.get(
    "/{brief_id}",
    response_model=BriefResponse,
    operation_id="getBrief",
    responses=problem_response_docs(401, 404, 422),
)
async def get_brief(
    brief_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BriefResponse:
    """Get a single brief by ID."""
    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if brief is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Brief not found",
        )  # type: ignore[return-value]
    return brief  # type: ignore[return-value]


@router.post(
    "",
    response_model=BriefResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createBrief",
    responses=problem_response_docs(401, 422, 503),
)
async def create_brief(
    body: BriefCreateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BriefResponse:
    """Generate and persist a new intelligence brief."""
    generator = BriefGenerator(
        llm_url=settings.llm_url,
        llm_model=settings.llm_model,
    )

    try:
        content_md = await generator.generate(
            query=body.query,
            events=[],
            indicators=[],
            entities=[],
        )
    except Exception as exc:
        return problem_response(
            request,
            status_code=503,
            code="dependency_unavailable",
            detail="Brief generation failed",
        )  # type: ignore[return-value]

    brief = Brief(
        title=body.query,
        content_md=content_md,
        target_query=body.query,
        generated_by="llm",
        model_id=settings.llm_model,
        requested_by=current_user.username,
    )
    db.add(brief)
    await db.flush()
    await db.commit()
    response.headers["Location"] = f"/api/v1/briefs/{brief.id}"
    return brief  # type: ignore[return-value]
