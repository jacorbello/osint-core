"""Ingest API routes — dispatch Celery ingest tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from osint_core.api.deps import get_current_user
from osint_core.api.middleware.auth import UserInfo
from osint_core.workers.ingest import ingest_source

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


@router.post("/source/{source_id}/run")
async def run_ingest(
    source_id: str,
    plan_id: str = Query(..., description="Plan ID to ingest against"),
    current_user: UserInfo = Depends(get_current_user),
) -> dict[str, Any]:
    """Dispatch a Celery task to ingest from the specified source.

    Returns the Celery task ID for tracking.
    """
    task = ingest_source.delay(source_id, plan_id)
    return {
        "task_id": task.id,
        "source_id": source_id,
        "plan_id": plan_id,
        "status": "dispatched",
    }
