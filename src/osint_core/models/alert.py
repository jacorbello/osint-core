"""Alert model — fired alerts from scoring/correlation rules."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Alert(UUIDMixin, TimestampMixin, Base):
    """An alert raised by the scoring or correlation engine."""

    __tablename__ = "alerts"

    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    indicator_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )

    route_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, default="open", server_default="open"
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    first_fired_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_fired_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    acked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    acked_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osint.plan_versions.id"), nullable=True
    )

    plan_version = relationship("PlanVersion", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acked', 'escalated', 'resolved')",
            name="status_check",
        ),
        Index("ix_alerts_fingerprint_last_fired", "fingerprint", last_fired_at.desc()),
    )
