"""Pydantic schemas for plan version resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import RetentionClassEnum


class PlanVersionResponse(BaseModel):
    """Serialized plan version for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    plan_id: str
    version: int
    content_hash: str
    content: dict[str, Any]
    retention_class: RetentionClassEnum

    git_commit_sha: str | None = None
    activated_at: datetime | None = None
    activated_by: str | None = None
    is_active: bool = False
    validation_result: dict[str, Any] | None = None

    created_at: datetime


class PlanValidationResult(BaseModel):
    """Result of validating a plan YAML against its JSON Schema."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    diff_summary: str | None = None
