"""Pydantic schemas for entity resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from osint_core.schemas.common import PaginatedResponse


class EntityResponse(BaseModel):
    """Serialized entity for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_type: str
    name: str
    aliases: list[str] = []
    attributes: dict[str, Any] = {}

    first_seen: datetime
    last_seen: datetime

    created_at: datetime


class EntityList(PaginatedResponse[EntityResponse]):
    """Paginated list of entities."""
