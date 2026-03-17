"""Pydantic schemas for job resources."""

import uuid
from datetime import datetime
from typing import Any

from enum import StrEnum

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse, JobStatusEnum


class JobKindEnum(StrEnum):
    """API-exposed asynchronous job kinds."""

    ingest = "ingest"
    rescore = "rescore"
    brief_generate = "brief_generate"


class JobResponse(BaseModel):
    """Serialized job for API responses."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: uuid.UUID
    kind: str = Field(validation_alias="job_type")
    status: JobStatusEnum

    celery_task_id: str | None = None
    k8s_job_name: str | None = None
    input: dict[str, Any] = Field(default_factory=dict, validation_alias="input_params")
    result: dict[str, Any] = Field(default_factory=dict, validation_alias="output")
    error: str | None = None
    retry_count: int
    retry_of: uuid.UUID | None = None

    next_retry_at: datetime | None = None
    idempotency_key: str | None = None

    plan_version_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    submitted_at: datetime = Field(validation_alias="created_at")
    submitted_by: str | None = None


class JobList(CollectionResponse):
    """Paginated list of jobs."""
    items: list[JobResponse]


class JobCreateRequest(BaseModel):
    """Submit an asynchronous platform job."""

    kind: JobKindEnum
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
