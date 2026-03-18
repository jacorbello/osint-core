"""Pydantic schemas for entity resources."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from osint_core.schemas.common import CollectionResponse


class EntityResponse(BaseModel):
    """Serialized entity for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    first_seen: datetime
    last_seen: datetime

    created_at: datetime


class EntityList(CollectionResponse):
    """Paginated list of entities."""
    items: list[EntityResponse]
