"""Common schema types shared across all API resources."""

from enum import StrEnum

from pydantic import BaseModel, Field


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
    partial_success = "partial_success"
    dead_letter = "dead_letter"


class RetentionClassEnum(StrEnum):
    """Data retention classes for plans and artifacts."""

    ephemeral = "ephemeral"
    standard = "standard"
    evidentiary = "evidentiary"


class PageInfo(BaseModel):
    """Offset pagination metadata."""

    offset: int = Field(ge=0, description="Zero-based offset of the current page")
    limit: int = Field(ge=1, description="Maximum number of items requested")
    total: int = Field(ge=0, description="Total number of items matching the query")
    has_more: bool = Field(description="Whether additional pages are available")


class CollectionResponse(BaseModel):
    """Generic collection response wrapper."""
    page: PageInfo


class FieldError(BaseModel):
    """A field-level validation or contract error."""

    field: str | None = Field(default=None, description="Body or query field that failed")
    message: str = Field(description="Human-readable error message")
    code: str | None = Field(default=None, description="Stable machine-readable error code")


class ProblemDetails(BaseModel):
    """RFC7807-style error payload with stable machine-readable codes."""

    type: str = Field(default="about:blank", description="Problem type URI")
    title: str = Field(description="Short summary of the problem")
    status: int = Field(description="HTTP status code")
    code: str = Field(description="Stable machine-readable application error code")
    detail: str = Field(description="Human-readable explanation")
    instance: str | None = Field(default=None, description="Request path for this error")
    request_id: str | None = Field(default=None, description="Request correlation identifier")
    errors: list[FieldError] = Field(default_factory=list)
