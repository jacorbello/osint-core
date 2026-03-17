"""Pydantic schemas for audit log resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse


class AuditLogResponse(BaseModel):
    """Serialized audit log entry for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    action: str
    actor: str | None = None
    actor_username: str | None = None
    actor_roles: list[str] | None = None

    resource_type: str | None = None
    resource_id: str | None = None

    details: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime


class AuditLogList(CollectionResponse):
    """Paginated list of audit log entries."""
    items: list[AuditLogResponse]
