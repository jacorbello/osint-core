"""Pydantic schemas for event resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import PaginatedResponse, SeverityEnum


class EventResponse(BaseModel):
    """Serialized event for API responses."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: uuid.UUID
    event_type: str
    source_id: str

    title: str | None = None
    summary: str | None = None
    raw_excerpt: str | None = None

    occurred_at: datetime | None = None
    ingested_at: datetime

    score: float | None = None
    severity: SeverityEnum | None = None

    dedupe_fingerprint: str
    plan_version_id: uuid.UUID | None = None

    # Geographic fields
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    region: str | None = None
    source_category: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")


class EventList(PaginatedResponse[EventResponse]):
    """Paginated list of events."""
