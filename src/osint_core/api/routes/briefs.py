"""Brief API routes."""

from __future__ import annotations

import logging
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
from osint_core.services.brief_generator import BriefContext, BriefGenerator, fetch_brief_context

logger = logging.getLogger(__name__)

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


@router.get(
    "/{brief_id}/pdf",
    operation_id="getBriefPdf",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF file"},
        **problem_response_docs(401, 404, 422, 503),
    },
)
async def get_brief_pdf(
    brief_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Response:
    """Export a brief as a PDF document.

    If the brief already has a cached PDF URI, the PDF is regenerated fresh
    from the current markdown content (ensuring the latest version).  The
    generated PDF is uploaded to MinIO and the URI is stored on the brief.
    """
    from osint_core.services.pdf_export import generate_and_upload_pdf, render_brief_pdf

    result = await db.execute(select(Brief).where(Brief.id == brief_id))
    brief = result.scalar_one_or_none()
    if brief is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Brief not found",
        )  # type: ignore[return-value]

    try:
        pdf_bytes = render_brief_pdf(
            brief.content_md,
            title=brief.title,
        )
    except Exception:
        logger.exception("PDF rendering failed for brief %s", brief_id)
        return problem_response(
            request,
            status_code=503,
            code="pdf_render_failed",
            detail="PDF rendering failed",
        )  # type: ignore[return-value]

    # Upload to MinIO and store URI (best-effort; don't fail the request).
    try:
        uri = generate_and_upload_pdf(
            str(brief.id),
            brief.content_md,
            title=brief.title,
        )
        brief.content_pdf_uri = uri
        await db.commit()
    except Exception:
        logger.warning("MinIO upload failed for brief %s; returning PDF directly", brief_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="brief-{brief_id}.pdf"',
        },
    )


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
    ctx: BriefContext = await fetch_brief_context(db, body.query)

    generator = BriefGenerator(
        vllm_url=settings.vllm_url,
        llm_model=settings.llm_model,
    )

    try:
        content_md, generated_by = await generator.generate(
            query=body.query,
            events=ctx.events,
            indicators=ctx.indicators,
            entities=ctx.entities,
        )
    except Exception:
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
        generated_by=generated_by,
        model_id=settings.llm_model,
        requested_by=current_user.username,
        event_ids=ctx.event_ids,
        entity_ids=ctx.entity_ids,
        indicator_ids=ctx.indicator_ids,
    )
    db.add(brief)
    await db.flush()
    await db.commit()
    response.headers["Location"] = f"/api/v1/briefs/{brief.id}"
    return brief  # type: ignore[return-value]
