"""Pydantic schemas for user preference and saved search resources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SavedSearchRequest(BaseModel):
    """Request body for creating a saved search."""

    name: str = Field(description="Human-readable name for the saved search")
    query: str = Field(description="Search query string")
    filters: dict[str, Any] = Field(
        default_factory=dict, description="Optional filter criteria"
    )
    alert_enabled: bool = Field(
        default=False, description="Whether to send alerts for new results"
    )


class SavedSearchResponse(BaseModel):
    """Serialized saved search in API responses."""

    id: str = Field(description="Unique identifier for the saved search")
    name: str
    query: str
    filters: dict[str, Any] = Field(default_factory=dict)
    alert_enabled: bool = False
    created_at: str = Field(description="ISO-8601 creation timestamp")


class PreferenceResponse(BaseModel):
    """Serialized user preference for API responses."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_sub: str
    notification_prefs: dict[str, Any] = Field(default_factory=dict)
    saved_searches: list[dict[str, Any]] = Field(default_factory=list)
    timezone: str = "UTC"
    created_at: datetime
    updated_at: datetime


class PreferenceUpdateRequest(BaseModel):
    """Request body for updating user preferences."""

    notification_prefs: dict[str, Any] | None = Field(
        default=None, description="Notification preferences (JSONB)"
    )
    timezone: str | None = Field(
        default=None, description="User timezone (e.g. 'America/New_York')"
    )
