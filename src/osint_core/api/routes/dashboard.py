"""Dashboard aggregate API routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.alert import Alert
from osint_core.models.event import Event
from osint_core.models.job import Job
from osint_core.models.lead import Lead
from osint_core.models.watch import Watch
from osint_core.schemas.common import JobStatusEnum, StatusEnum
from osint_core.schemas.lead import LeadStatusEnum
from osint_core.schemas.ui import DashboardSummaryResponse, EventSummary
from osint_core.schemas.watch import WatchStatusEnum

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


async def _group_counts(
    db: AsyncSession,
    *,
    column: Any,
) -> dict[str, int]:
    """Count rows grouped by a string-valued column."""
    result = await db.execute(select(column, func.count()).group_by(column))
    return {str(value): count for value, count in result.all() if value is not None}


def _init_counts(values: list[str]) -> dict[str, int]:
    return {value: 0 for value in values}


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    operation_id="getDashboardSummary",
)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> DashboardSummaryResponse:
    """Return aggregated counters for UI dashboard cards."""
    del current_user
    alerts = _init_counts([status.value for status in StatusEnum])
    watches = _init_counts([status.value for status in WatchStatusEnum])
    leads = _init_counts([status.value for status in LeadStatusEnum])
    jobs = _init_counts([status.value for status in JobStatusEnum])

    alerts.update(await _group_counts(db, column=Alert.status))
    watches.update(await _group_counts(db, column=Watch.status))
    leads.update(await _group_counts(db, column=Lead.status))
    jobs.update(await _group_counts(db, column=Job.status))

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    events_24h = await db.execute(
        select(func.count()).select_from(Event).where(Event.ingested_at >= cutoff)
    )

    return DashboardSummaryResponse(
        alerts=alerts,
        watches=watches,
        leads=leads,
        jobs=jobs,
        events=EventSummary(last_24h_count=events_24h.scalar_one()),
        updated_at=datetime.now(UTC),
    )
