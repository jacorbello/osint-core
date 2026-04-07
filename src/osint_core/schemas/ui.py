"""UI-oriented aggregate and utility schemas."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.alert import AlertResponse
from osint_core.schemas.common import StatusEnum
from osint_core.schemas.entity import EntityResponse
from osint_core.schemas.event import EventResponse
from osint_core.schemas.indicator import IndicatorResponse
from osint_core.schemas.lead import LeadStatusEnum


class MeResponse(BaseModel):
    """Authenticated user identity for UI session bootstrap."""

    sub: str
    username: str
    roles: list[str] = Field(default_factory=list)
    auth_disabled: bool


class FacetBucket(BaseModel):
    """Single facet value and its count."""

    value: str
    count: int = Field(ge=0)


class FacetsResponse(BaseModel):
    """Facet buckets grouped by field name."""

    facets: dict[str, list[FacetBucket]]
    applied_filters: dict[str, Any] = Field(default_factory=dict)


class EventSummary(BaseModel):
    """Dashboard event summary metrics."""

    last_24h_count: int = Field(ge=0)


class DashboardSummaryResponse(BaseModel):
    """Aggregated dashboard counters for primary UI cards."""

    alerts: dict[str, int]
    watches: dict[str, int]
    leads: dict[str, int]
    jobs: dict[str, int]
    events: EventSummary
    updated_at: datetime


class ExportFormatEnum(StrEnum):
    """Supported export response formats."""

    csv = "csv"
    json = "json"


class BulkActionRequestBase(BaseModel):
    """Shared request fields for bulk status actions."""

    ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=1000,
        description="Resource IDs to update (max 1000 per request)",
    )
    dry_run: bool = Field(default=False, description="Validate and preview without persisting")


class AlertBulkUpdateRequest(BulkActionRequestBase):
    """Bulk update request for alert status transitions."""

    target_status: StatusEnum


class LeadBulkUpdateRequest(BulkActionRequestBase):
    """Bulk update request for lead status transitions."""

    target_status: LeadStatusEnum


class BulkUpdateChange(BaseModel):
    """One successful status transition."""

    id: uuid.UUID
    from_status: str
    to_status: str


class BulkUpdateIssue(BaseModel):
    """One skipped or failed bulk item."""

    id: uuid.UUID
    reason_code: str
    detail: str


class BulkUpdateSummary(BaseModel):
    """Aggregate outcome counters for bulk updates."""

    requested: int
    processed: int
    updated: int
    skipped: int
    errors: int


class BulkUpdateResponse(BaseModel):
    """Best-effort status update results."""

    summary: BulkUpdateSummary
    updated: list[BulkUpdateChange] = Field(default_factory=list)
    skipped: list[BulkUpdateIssue] = Field(default_factory=list)
    errors: list[BulkUpdateIssue] = Field(default_factory=list)


class EventRelatedMeta(BaseModel):
    """Relationship section counts."""

    alert_count: int
    entity_count: int
    indicator_count: int


class EventRelatedResponse(BaseModel):
    """Single-call event plus linked records used by investigation UIs."""

    event: EventResponse
    alerts: list[AlertResponse] = Field(default_factory=list)
    entities: list[EntityResponse] = Field(default_factory=list)
    indicators: list[IndicatorResponse] = Field(default_factory=list)
    meta: EventRelatedMeta


class StreamEventPayload(BaseModel):
    """Structured envelope emitted for realtime SSE updates."""

    type: str
    resource: str
    id: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
