"""Lead API routes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.lead import Lead, LeadStatusEnum
from osint_core.schemas.lead import LeadListResponse, LeadResponse, LeadUpdateRequest

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])

# Valid status transitions: maps current status to allowed next statuses.
_STATUS_TRANSITIONS: dict[str, set[str]] = {
    LeadStatusEnum.new: {LeadStatusEnum.reviewing, LeadStatusEnum.declined, LeadStatusEnum.stale},
    LeadStatusEnum.reviewing: {
        LeadStatusEnum.qualified,
        LeadStatusEnum.declined,
        LeadStatusEnum.stale,
    },
    LeadStatusEnum.qualified: {
        LeadStatusEnum.contacted,
        LeadStatusEnum.declined,
        LeadStatusEnum.stale,
    },
    LeadStatusEnum.contacted: {
        LeadStatusEnum.retained,
        LeadStatusEnum.declined,
        LeadStatusEnum.stale,
    },
    LeadStatusEnum.retained: set(),
    LeadStatusEnum.declined: set(),
    LeadStatusEnum.stale: {LeadStatusEnum.reviewing},
}


@router.get(
    "",
    response_model=LeadListResponse,
    operation_id="listLeads",
    responses=problem_response_docs(401, 422),
)
async def list_leads(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    lead_type: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> LeadListResponse:
    """List leads with optional filters."""
    stmt = select(Lead)
    count_stmt = select(func.count()).select_from(Lead)

    if status is not None:
        stmt = stmt.where(Lead.status == status)
        count_stmt = count_stmt.where(Lead.status == status)
    if jurisdiction is not None:
        stmt = stmt.where(Lead.jurisdiction == jurisdiction)
        count_stmt = count_stmt.where(Lead.jurisdiction == jurisdiction)
    if lead_type is not None:
        stmt = stmt.where(Lead.lead_type == lead_type)
        count_stmt = count_stmt.where(Lead.lead_type == lead_type)
    if plan_id is not None:
        stmt = stmt.where(Lead.plan_id == plan_id)
        count_stmt = count_stmt.where(Lead.plan_id == plan_id)
    if date_from is not None:
        stmt = stmt.where(Lead.first_surfaced_at >= date_from)
        count_stmt = count_stmt.where(Lead.first_surfaced_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Lead.first_surfaced_at <= date_to)
        count_stmt = count_stmt.where(Lead.first_surfaced_at <= date_to)

    stmt = stmt.order_by(Lead.first_surfaced_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return LeadListResponse(
        items=items, page=collection_page(offset=offset, limit=limit, total=total)
    )


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    operation_id="getLead",
    responses=problem_response_docs(401, 404, 422),
)
async def get_lead(
    lead_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> LeadResponse:
    """Get a single lead by ID with full citations."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Lead not found",
        )  # type: ignore[return-value]
    return lead  # type: ignore[return-value]


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    operation_id="updateLead",
    responses=problem_response_docs(401, 404, 422),
)
async def update_lead(
    lead_id: UUID,
    body: LeadUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> LeadResponse:
    """Update a lead's status with transition validation."""
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if lead is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Lead not found",
        )  # type: ignore[return-value]

    allowed = _STATUS_TRANSITIONS.get(lead.status, set())
    if body.status not in allowed:
        return problem_response(
            request,
            status_code=422,
            code="invalid_status_transition",
            detail=f"Cannot transition from '{lead.status}' to '{body.status}'",
        )  # type: ignore[return-value]

    lead.status = body.status
    await db.commit()
    await db.refresh(lead)
    return lead  # type: ignore[return-value]
