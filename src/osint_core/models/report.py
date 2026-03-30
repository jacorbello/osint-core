"""Report model — tracks generated prospecting report artifacts."""

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Report(UUIDMixin, TimestampMixin, Base):
    """A generated prospecting report artifact."""

    __tablename__ = "reports"

    artifact_uri: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    lead_count: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_reports_plan_id", "plan_id"),
        Index("ix_reports_generated_at", "generated_at"),
    )
