"""Lead model — prospecting opportunities tracked through a qualification pipeline."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Float, Index, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class LeadTypeEnum(enum.StrEnum):
    """Type of constitutional lead."""

    incident = "incident"
    policy = "policy"


class LeadStatusEnum(enum.StrEnum):
    """Lifecycle status of a lead."""

    new = "new"
    reviewing = "reviewing"
    qualified = "qualified"
    contacted = "contacted"
    retained = "retained"
    declined = "declined"
    stale = "stale"


class Lead(UUIDMixin, TimestampMixin, Base):
    """A prospecting lead surfaced from OSINT events."""

    __tablename__ = "leads"

    lead_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")

    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    constitutional_basis: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    institution: Mapped[str | None] = mapped_column(Text, nullable=True)

    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedupe_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    first_surfaced_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    reported_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "lead_type IN ('incident', 'policy')",
            name="lead_type_check",
        ),
        CheckConstraint(
            "status IN ('new', 'reviewing', 'qualified', 'contacted', "
            "'retained', 'declined', 'stale')",
            name="lead_status_check",
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="lead_severity_check",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="lead_confidence_range",
        ),
        Index("ix_leads_dedupe_fingerprint", "dedupe_fingerprint", unique=True),
        Index("ix_leads_status", "status"),
        Index("ix_leads_jurisdiction", "jurisdiction"),
        Index("ix_leads_reported_at", "reported_at"),
        Index("ix_leads_plan_id", "plan_id"),
    )
