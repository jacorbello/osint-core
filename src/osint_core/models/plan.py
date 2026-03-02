"""PlanVersion model — versioned intelligence collection plans."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class PlanVersion(UUIDMixin, TimestampMixin, Base):
    """A versioned snapshot of an intelligence collection plan."""

    __tablename__ = "plan_versions"

    plan_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    retention_class: Mapped[str] = mapped_column(Text, nullable=False)

    git_commit_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    validation_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("plan_id", "version"),
        CheckConstraint(
            "retention_class IN ('ephemeral', 'standard', 'evidentiary')",
            name="retention_class_check",
        ),
    )
