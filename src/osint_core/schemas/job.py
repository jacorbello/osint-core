"""Pydantic schemas for job resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from osint_core.schemas.common import JobStatusEnum, PaginatedResponse


class JobResponse(BaseModel):
    """Serialized job for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    job_type: str
    status: JobStatusEnum

    celery_task_id: str | None = None
    k8s_job_name: str | None = None
    input_params: dict[str, Any] = {}
    output: dict[str, Any] = {}
    error: str | None = None
    retry_count: int

    next_retry_at: datetime | None = None
    idempotency_key: str | None = None

    plan_version_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    created_at: datetime


class JobList(PaginatedResponse[JobResponse]):
    """Paginated list of jobs."""
