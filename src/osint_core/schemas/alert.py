"""Pydantic schemas for alert resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from osint_core.schemas.common import PaginatedResponse, SeverityEnum, StatusEnum


class AlertResponse(BaseModel):
    """Serialized alert for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    fingerprint: str
    severity: SeverityEnum
    title: str
    summary: str | None = None

    event_ids: list[uuid.UUID] = []
    indicator_ids: list[uuid.UUID] = []
    entity_ids: list[uuid.UUID] = []

    route_name: str | None = None
    status: StatusEnum
    occurrences: int

    first_fired_at: datetime
    last_fired_at: datetime
    acked_at: datetime | None = None
    acked_by: str | None = None

    plan_version_id: uuid.UUID | None = None

    created_at: datetime


class AlertList(PaginatedResponse[AlertResponse]):
    """Paginated list of alerts."""


class AlertAckRequest(BaseModel):
    """Request body for acknowledging an alert."""

    acked_by: str = Field(description="Username or ID of the person acknowledging the alert")


class AlertEscalateRequest(BaseModel):
    """Request body for escalating an alert."""

    reason: str = Field(description="Reason for escalation")
    escalate_to: str | None = Field(
        default=None, description="Target user or team for escalation"
    )
