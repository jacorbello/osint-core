"""Pydantic schemas for indicator resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse


class IndicatorResponse(BaseModel):
    """Serialized indicator for API responses."""

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: uuid.UUID
    indicator_type: str
    value: str
    confidence: float

    first_seen: datetime
    last_seen: datetime

    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")

    created_at: datetime


class IndicatorList(CollectionResponse):
    """Paginated list of indicators."""
    items: list[IndicatorResponse]
