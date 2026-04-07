"""Lead API routes."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.api.realtime import publish_event
from osint_core.models.lead import Lead, LeadStatusEnum
from osint_core.schemas.lead import LeadListResponse, LeadResponse, LeadUpdateRequest
from osint_core.schemas.ui import (
    BulkUpdateChange,
    BulkUpdateIssue,
    BulkUpdateResponse,
    BulkUpdateSummary,
    ExportFormatEnum,
    FacetBucket,
    FacetsResponse,
    LeadBulkUpdateRequest,
)

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


def _serialize_lead_rows(leads: list[Lead]) -> list[dict[str, Any]]:
    """Convert lead ORM objects to JSON-safe dicts."""
    rows: list[dict[str, Any]] = []
    for item in leads:
        row = LeadResponse.model_validate(item).model_dump(mode="json")
        rows.append(row)
    return rows


def _render_csv(rows: list[dict[str, Any]], *, fieldnames: list[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    json.dumps(value)
                    if isinstance(value, (list, dict))
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue()


async def _facet_counts(
    db: AsyncSession,
    *,
    column: Any,
    filters: list[Any],
) -> list[FacetBucket]:
    """Build facet buckets for a single lead column."""
    stmt = (
        select(column, func.count())
        .where(*filters, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column.asc())
    )
    result = await db.execute(stmt)
    return [FacetBucket(value=str(value), count=count) for value, count in result.all()]


@router.get(
    "/facets",
    response_model=FacetsResponse,
    operation_id="listLeadFacets",
    responses=problem_response_docs(401, 422),
)
async def list_lead_facets(
    status: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    lead_type: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> FacetsResponse:
    """List filter facets for lead pipeline views."""
    del current_user
    filters = []
    applied_filters: dict[str, str] = {}

    if status is not None:
        filters.append(Lead.status == status)
        applied_filters["status"] = status
    if jurisdiction is not None:
        filters.append(Lead.jurisdiction == jurisdiction)
        applied_filters["jurisdiction"] = jurisdiction
    if lead_type is not None:
        filters.append(Lead.lead_type == lead_type)
        applied_filters["lead_type"] = lead_type
    if plan_id is not None:
        filters.append(Lead.plan_id == plan_id)
        applied_filters["plan_id"] = plan_id
    if date_from is not None:
        filters.append(Lead.first_surfaced_at >= date_from)
        applied_filters["date_from"] = date_from.isoformat()
    if date_to is not None:
        filters.append(Lead.first_surfaced_at <= date_to)
        applied_filters["date_to"] = date_to.isoformat()

    facets = {
        "status": await _facet_counts(db, column=Lead.status, filters=filters),
        "lead_type": await _facet_counts(db, column=Lead.lead_type, filters=filters),
        "jurisdiction": await _facet_counts(db, column=Lead.jurisdiction, filters=filters),
        "plan_id": await _facet_counts(db, column=Lead.plan_id, filters=filters),
    }
    return FacetsResponse(facets=facets, applied_filters=applied_filters)


@router.post(
    "/bulk-update",
    response_model=BulkUpdateResponse,
    operation_id="bulkUpdateLeads",
    responses=problem_response_docs(401, 422),
)
async def bulk_update_leads(
    body: LeadBulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BulkUpdateResponse:
    """Bulk update lead statuses with best-effort per-item handling.

    Uses stable reason codes in ``skipped``/``errors`` items:
    ``not_found``, ``already_in_target``, ``invalid_transition``, ``update_failed``.
    """
    del current_user
    deduped_ids: list[UUID] = []
    seen: set[UUID] = set()
    for lead_id in body.ids:
        if lead_id not in seen:
            seen.add(lead_id)
            deduped_ids.append(lead_id)

    result = await db.execute(select(Lead).where(Lead.id.in_(deduped_ids)))
    existing = {item.id: item for item in result.scalars().all()}

    updated: list[BulkUpdateChange] = []
    skipped: list[BulkUpdateIssue] = []
    errors: list[BulkUpdateIssue] = []
    updated_lead_ids: list[UUID] = []

    for lead_id in deduped_ids:
        lead = existing.get(lead_id)
        if lead is None:
            skipped.append(
                BulkUpdateIssue(
                    id=lead_id,
                    reason_code="not_found",
                    detail="Lead not found",
                )
            )
            continue

        from_status = str(lead.status)
        to_status = body.target_status.value

        if from_status == to_status:
            skipped.append(
                BulkUpdateIssue(
                    id=lead_id,
                    reason_code="already_in_target",
                    detail=f"Lead is already in status '{from_status}'",
                )
            )
            continue

        allowed = _STATUS_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            skipped.append(
                BulkUpdateIssue(
                    id=lead_id,
                    reason_code="invalid_transition",
                    detail=f"Cannot transition from '{from_status}' to '{to_status}'",
                )
            )
            continue

        try:
            if not body.dry_run:
                lead.status = to_status
                updated_lead_ids.append(lead.id)
            updated.append(
                BulkUpdateChange(
                    id=lead.id,
                    from_status=from_status,
                    to_status=to_status,
                )
            )
        except Exception as exc:
            errors.append(
                BulkUpdateIssue(
                    id=lead_id,
                    reason_code="update_failed",
                    detail=str(exc),
                )
            )

    if not body.dry_run and updated_lead_ids:
        await db.commit()
        for lead_id in updated_lead_ids:
            await publish_event(
                event_type="lead.updated",
                resource="lead",
                resource_id=lead_id,
                payload={"to_status": body.target_status.value, "bulk": True},
            )

    summary = BulkUpdateSummary(
        requested=len(body.ids),
        processed=len(deduped_ids),
        updated=len(updated),
        skipped=len(skipped),
        errors=len(errors),
    )
    return BulkUpdateResponse(summary=summary, updated=updated, skipped=skipped, errors=errors)


@router.get(
    "/export",
    operation_id="exportLeads",
    responses=problem_response_docs(401, 422),
)
async def export_leads(
    format: ExportFormatEnum = Query(default=ExportFormatEnum.csv),
    status: str | None = Query(default=None),
    jurisdiction: str | None = Query(default=None),
    lead_type: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max rows to export"),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Response:
    """Export lead rows as CSV or JSON."""
    del current_user
    stmt = select(Lead)

    if status is not None:
        stmt = stmt.where(Lead.status == status)
    if jurisdiction is not None:
        stmt = stmt.where(Lead.jurisdiction == jurisdiction)
    if lead_type is not None:
        stmt = stmt.where(Lead.lead_type == lead_type)
    if plan_id is not None:
        stmt = stmt.where(Lead.plan_id == plan_id)
    if date_from is not None:
        stmt = stmt.where(Lead.first_surfaced_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Lead.first_surfaced_at <= date_to)

    stmt = stmt.order_by(Lead.first_surfaced_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = _serialize_lead_rows(list(result.scalars().all()))

    if format == ExportFormatEnum.json:
        return JSONResponse(content=rows)

    fieldnames = list(LeadResponse.model_fields.keys())
    csv_data = _render_csv(rows, fieldnames=fieldnames)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="leads-export.csv"'},
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
    await publish_event(
        event_type="lead.updated",
        resource="lead",
        resource_id=lead.id,
        payload={"to_status": body.status},
    )
    return lead  # type: ignore[return-value]
