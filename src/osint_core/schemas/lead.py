"""Pydantic schemas for lead resources."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse, SeverityEnum


class LeadTypeEnum(StrEnum):
    """Type of constitutional lead."""

    incident = "incident"
    policy = "policy"


class LeadStatusEnum(StrEnum):
    """Lifecycle status of a lead."""

    new = "new"
    reviewing = "reviewing"
    qualified = "qualified"
    contacted = "contacted"
    retained = "retained"
    declined = "declined"
    stale = "stale"


class LeadResponse(BaseModel):
    """Serialized lead for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    lead_type: LeadTypeEnum
    status: LeadStatusEnum

    title: str
    summary: str | None = None
    constitutional_basis: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    institution: str | None = None

    severity: SeverityEnum | None = None
    confidence: float | None = None
    dedupe_fingerprint: str

    plan_id: str | None = None
    event_ids: list[uuid.UUID] = Field(default_factory=list)
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    citations: dict[str, Any] | None = None

    report_id: uuid.UUID | None = None

    first_surfaced_at: datetime
    last_updated_at: datetime
    reported_at: datetime | None = None

    created_at: datetime


class LeadListResponse(CollectionResponse):
    """Paginated list of leads."""

    items: list[LeadResponse]


class LeadUpdateRequest(BaseModel):
    """Request body for updating lead lifecycle state."""

    status: LeadStatusEnum = Field(description="New lifecycle status for the lead")
