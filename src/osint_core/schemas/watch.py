"""Pydantic schemas for watch resources."""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from osint_core.schemas.common import PaginatedResponse


class WatchTypeEnum(StrEnum):
    persistent = "persistent"
    dynamic = "dynamic"


class WatchStatusEnum(StrEnum):
    active = "active"
    paused = "paused"
    expired = "expired"
    promoted = "promoted"


class WatchCreateRequest(BaseModel):
    name: str
    region: str | None = None
    country_codes: list[str] | None = None
    bounding_box: dict[str, float] | None = None
    keywords: list[str] | None = None
    source_filter: list[str] | None = None
    severity_threshold: str = "medium"
    plan_id: str | None = None
    ttl_hours: int | None = None


class WatchUpdateRequest(BaseModel):
    status: WatchStatusEnum | None = None
    region: str | None = None
    country_codes: list[str] | None = None
    bounding_box: dict[str, float] | None = None
    keywords: list[str] | None = None
    source_filter: list[str] | None = None
    severity_threshold: str | None = None
    ttl_hours: int | None = None


class WatchResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    watch_type: WatchTypeEnum
    status: WatchStatusEnum
    region: str | None = None
    country_codes: list[str] | None = None
    bounding_box: dict[str, float] | None = None
    keywords: list[str] | None = None
    source_filter: list[str] | None = None
    severity_threshold: str
    plan_id: str | None = None
    ttl_hours: int | None = None
    created_at: datetime
    expires_at: datetime | None = None
    promoted_at: datetime | None = None
    created_by: str


class WatchList(PaginatedResponse[WatchResponse]):
    pass
