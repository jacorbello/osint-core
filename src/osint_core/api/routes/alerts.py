"""Alert API routes."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
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
from osint_core.models.alert import Alert
from osint_core.schemas.alert import AlertList, AlertResponse, AlertUpdateRequest
from osint_core.schemas.ui import (
    AlertBulkUpdateRequest,
    BulkUpdateChange,
    BulkUpdateIssue,
    BulkUpdateResponse,
    BulkUpdateSummary,
    ExportFormatEnum,
    FacetBucket,
    FacetsResponse,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get(
    "",
    response_model=AlertList,
    operation_id="listAlerts",
    responses=problem_response_docs(401, 422),
)
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertList:
    """List alerts with optional lifecycle and severity filters."""
    stmt = select(Alert)
    count_stmt = select(func.count()).select_from(Alert)

    if status is not None:
        stmt = stmt.where(Alert.status == status)
        count_stmt = count_stmt.where(Alert.status == status)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
        count_stmt = count_stmt.where(Alert.severity == severity)

    stmt = stmt.order_by(Alert.last_fired_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return AlertList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


def _serialize_alert_rows(alerts: list[Alert]) -> list[dict[str, Any]]:
    """Convert alert ORM objects to JSON-safe dicts."""
    rows: list[dict[str, Any]] = []
    for item in alerts:
        row = AlertResponse.model_validate(item).model_dump(mode="json")
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
    """Build facet buckets for a single alert column."""
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
    operation_id="listAlertFacets",
    responses=problem_response_docs(401, 422),
)
async def list_alert_facets(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> FacetsResponse:
    """List filter facets for alert triage views."""
    del current_user
    filters = []
    applied_filters: dict[str, str] = {}

    if status is not None:
        filters.append(Alert.status == status)
        applied_filters["status"] = status
    if severity is not None:
        filters.append(Alert.severity == severity)
        applied_filters["severity"] = severity

    facets = {
        "status": await _facet_counts(db, column=Alert.status, filters=filters),
        "severity": await _facet_counts(db, column=Alert.severity, filters=filters),
        "route_name": await _facet_counts(db, column=Alert.route_name, filters=filters),
    }
    return FacetsResponse(facets=facets, applied_filters=applied_filters)


@router.post(
    "/bulk-update",
    response_model=BulkUpdateResponse,
    operation_id="bulkUpdateAlerts",
    responses=problem_response_docs(401, 422),
)
async def bulk_update_alerts(
    body: AlertBulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> BulkUpdateResponse:
    """Bulk update alert statuses with best-effort per-item handling.

    Uses stable reason codes in ``skipped``/``errors`` items:
    ``not_found``, ``already_in_target``, ``invalid_transition``, ``update_failed``.
    """
    deduped_ids: list[UUID] = []
    seen: set[UUID] = set()
    for alert_id in body.ids:
        if alert_id not in seen:
            seen.add(alert_id)
            deduped_ids.append(alert_id)

    result = await db.execute(select(Alert).where(Alert.id.in_(deduped_ids)))
    existing = {item.id: item for item in result.scalars().all()}

    updated: list[BulkUpdateChange] = []
    skipped: list[BulkUpdateIssue] = []
    errors: list[BulkUpdateIssue] = []
    updated_alert_ids: list[UUID] = []

    for alert_id in deduped_ids:
        alert = existing.get(alert_id)
        if alert is None:
            skipped.append(
                BulkUpdateIssue(
                    id=alert_id,
                    reason_code="not_found",
                    detail="Alert not found",
                )
            )
            continue

        from_status = str(alert.status)
        to_status = body.target_status.value

        if from_status == to_status:
            skipped.append(
                BulkUpdateIssue(
                    id=alert_id,
                    reason_code="already_in_target",
                    detail=f"Alert is already in status '{from_status}'",
                )
            )
            continue

        if to_status == "resolved" and from_status == "open":
            skipped.append(
                BulkUpdateIssue(
                    id=alert_id,
                    reason_code="invalid_transition",
                    detail="Open alerts must be acknowledged or escalated before resolution",
                )
            )
            continue

        try:
            if not body.dry_run:
                alert.status = to_status
                if to_status == "acked":
                    alert.acked_at = datetime.now(UTC)
                    alert.acked_by = current_user.username
                updated_alert_ids.append(alert.id)
            updated.append(
                BulkUpdateChange(
                    id=alert.id,
                    from_status=from_status,
                    to_status=to_status,
                )
            )
        except Exception as exc:
            errors.append(
                BulkUpdateIssue(
                    id=alert_id,
                    reason_code="update_failed",
                    detail=str(exc),
                )
            )

    if not body.dry_run and updated_alert_ids:
        await db.commit()
        for alert_id in updated_alert_ids:
            await publish_event(
                event_type="alert.updated",
                resource="alert",
                resource_id=alert_id,
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
    operation_id="exportAlerts",
    responses=problem_response_docs(401, 422),
)
async def export_alerts(
    format: ExportFormatEnum = Query(default=ExportFormatEnum.csv),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max rows to export"),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Response:
    """Export alert rows as CSV or JSON."""
    del current_user
    stmt = select(Alert)
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if severity is not None:
        stmt = stmt.where(Alert.severity == severity)
    stmt = stmt.order_by(Alert.last_fired_at.desc()).limit(limit)

    result = await db.execute(stmt)
    rows = _serialize_alert_rows(list(result.scalars().all()))

    if format == ExportFormatEnum.json:
        return JSONResponse(content=rows)

    fieldnames = list(AlertResponse.model_fields.keys())
    csv_data = _render_csv(rows, fieldnames=fieldnames)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alerts-export.csv"'},
    )


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    operation_id="getAlert",
    responses=problem_response_docs(401, 404, 422),
)
async def get_alert(
    alert_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Get a single alert by ID."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Alert not found",
        )  # type: ignore[return-value]
    return alert  # type: ignore[return-value]


@router.patch(
    "/{alert_id}",
    response_model=AlertResponse,
    operation_id="updateAlert",
    responses=problem_response_docs(401, 404, 409, 422),
)
async def update_alert(
    alert_id: UUID,
    body: AlertUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Update the lifecycle state of an alert."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Alert not found",
        )  # type: ignore[return-value]

    if alert.status == body.status:
        return problem_response(
            request,
            status_code=409,
            code="invalid_state_transition",
            detail=f"Alert is already in status '{alert.status}'",
        )  # type: ignore[return-value]

    if body.status == "acked":
        alert.acked_at = datetime.now(UTC)
        alert.acked_by = current_user.username
    elif body.status == "resolved" and alert.status == "open":
        return problem_response(
            request,
            status_code=409,
            code="invalid_state_transition",
            detail="Open alerts must be acknowledged or escalated before resolution",
        )  # type: ignore[return-value]

    alert.status = body.status
    await db.commit()
    await db.refresh(alert)
    await publish_event(
        event_type="alert.updated",
        resource="alert",
        resource_id=alert.id,
        payload={"to_status": body.status},
    )
    return alert  # type: ignore[return-value]
