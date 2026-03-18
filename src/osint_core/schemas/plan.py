"""Pydantic schemas for plan version resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from osint_core.schemas.common import CollectionResponse, RetentionClassEnum


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


class PlanCreateRequest(BaseModel):
    """Create a new plan version from YAML content."""

    yaml: str = Field(description="Plan YAML document")
    git_commit_sha: str | None = None
    activate: bool = True


class PlanActivationRequest(BaseModel):
    """Update which version is active for a plan."""

    version_id: uuid.UUID | None = None
    rollback: bool = False

    @model_validator(mode="after")
    def validate_action(self) -> "PlanActivationRequest":
        if self.rollback and self.version_id is not None:
            raise ValueError("version_id cannot be set when rollback=true")
        if not self.rollback and self.version_id is None:
            raise ValueError("version_id is required unless rollback=true")
        return self


class PlanVersionList(CollectionResponse):
    """Paginated list of plan versions."""
    items: list[PlanVersionResponse]
