"""Pydantic schemas for indicator resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from osint_core.schemas.common import PaginatedResponse


class IndicatorResponse(BaseModel):
    """Serialized indicator for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    indicator_type: str
    value: str
    confidence: float

    first_seen: datetime
    last_seen: datetime

    sources: list[str] = []
    metadata: dict[str, Any] = {}

    created_at: datetime


class IndicatorList(PaginatedResponse[IndicatorResponse]):
    """Paginated list of indicators."""
