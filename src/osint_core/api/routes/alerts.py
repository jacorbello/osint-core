"""Alert API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.alert import Alert
from osint_core.schemas.alert import (
    AlertAckRequest,
    AlertEscalateRequest,
    AlertList,
    AlertResponse,
)

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=AlertList)
async def list_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertList:
    """List alerts with optional status and severity filters."""
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

    page = (offset // limit) + 1
    pages = (total + limit - 1) // limit if total > 0 else 0

    return AlertList(items=items, total=total, page=page, page_size=limit, pages=pages)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Get a single alert by ID."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert  # type: ignore[return-value]


@router.post("/{alert_id}/ack", response_model=AlertResponse)
async def ack_alert(
    alert_id: UUID,
    body: AlertAckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Acknowledge an alert."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "acked"
    alert.acked_at = datetime.now(UTC)
    alert.acked_by = body.acked_by
    await db.flush()
    await db.commit()
    return alert  # type: ignore[return-value]


@router.post("/{alert_id}/escalate", response_model=AlertResponse)
async def escalate_alert(
    alert_id: UUID,
    body: AlertEscalateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Escalate an alert."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "escalated"
    await db.flush()
    await db.commit()
    return alert  # type: ignore[return-value]


@router.post("/{alert_id}/resolve", response_model=AlertResponse)
async def resolve_alert(
    alert_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AlertResponse:
    """Resolve an alert."""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.status = "resolved"
    await db.flush()
    await db.commit()
    return alert  # type: ignore[return-value]
