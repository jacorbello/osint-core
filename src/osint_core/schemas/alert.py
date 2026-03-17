"""Pydantic schemas for alert resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse, SeverityEnum, StatusEnum


class AlertResponse(BaseModel):
    """Serialized alert for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    fingerprint: str
    severity: SeverityEnum
    title: str
    summary: str | None = None

    event_ids: list[uuid.UUID] = Field(default_factory=list)
    indicator_ids: list[uuid.UUID] = Field(default_factory=list)
    entity_ids: list[uuid.UUID] = Field(default_factory=list)

    route_name: str | None = None
    status: StatusEnum
    occurrences: int

    first_fired_at: datetime
    last_fired_at: datetime
    acked_at: datetime | None = None
    acked_by: str | None = None

    plan_version_id: uuid.UUID | None = None

    created_at: datetime


class AlertList(CollectionResponse):
    """Paginated list of alerts."""
    items: list[AlertResponse]


class AlertUpdateRequest(BaseModel):
    """Request body for updating alert lifecycle state."""

    status: StatusEnum = Field(description="New lifecycle status for the alert")
