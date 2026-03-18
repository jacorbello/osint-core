"""Alert API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.alert import Alert
from osint_core.schemas.alert import AlertList, AlertResponse, AlertUpdateRequest

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
    return alert  # type: ignore[return-value]
