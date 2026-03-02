"""Pydantic schemas for intelligence brief resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from osint_core.schemas.common import PaginatedResponse


class BriefResponse(BaseModel):
    """Serialized intelligence brief for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    content_md: str
    content_pdf_uri: str | None = None
    target_query: str | None = None

    event_ids: list[uuid.UUID] = []
    entity_ids: list[uuid.UUID] = []
    indicator_ids: list[uuid.UUID] = []

    generated_by: str
    model_id: str | None = None

    plan_version_id: uuid.UUID | None = None
    requested_by: str | None = None

    created_at: datetime


class BriefList(PaginatedResponse[BriefResponse]):
    """Paginated list of briefs."""


class BriefGenerateRequest(BaseModel):
    """Request body for generating a new intelligence brief."""

    query: str = Field(description="Natural language query describing what the brief should cover")
