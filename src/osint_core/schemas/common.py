"""Common schema types shared across all API resources."""

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class SeverityEnum(StrEnum):
    """Severity levels for events and alerts."""

    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class StatusEnum(StrEnum):
    """Alert lifecycle statuses."""

    open = "open"
    acked = "acked"
    escalated = "escalated"
    resolved = "resolved"


class JobStatusEnum(StrEnum):
    """Job lifecycle statuses."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    dead_letter = "dead_letter"


class RetentionClassEnum(StrEnum):
    """Data retention classes for plans and artifacts."""

    ephemeral = "ephemeral"
    standard = "standard"
    evidentiary = "evidentiary"


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int = Field(ge=0, description="Total number of items matching the query")
    page: int = Field(ge=1, description="Current page number (1-indexed)")
    page_size: int = Field(ge=1, description="Number of items per page")
    pages: int = Field(ge=0, description="Total number of pages")
