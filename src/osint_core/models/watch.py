"""Watch model — persistent and dynamic regional monitors."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osint_core.models.base import Base, TimestampMixin, UUIDMixin

# Association table for watch <-> event
watch_events = Table(
    "watch_events",
    Base.metadata,
    Column(
        "watch_id", UUID(as_uuid=True),
        ForeignKey("osint.watches.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "event_id", UUID(as_uuid=True),
        ForeignKey("osint.events.id", ondelete="CASCADE"), primary_key=True,
    ),
)


class Watch(UUIDMixin, TimestampMixin, Base):
    """A regional or topic-based intelligence watch."""

    __tablename__ = "watches"

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    watch_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")

    region: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_codes: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text()), nullable=True
    )
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(Text()), nullable=True)
    source_filter: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text()), nullable=True
    )
    severity_threshold: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="medium"
    )

    plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    ttl_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    promoted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="manual"
    )

    events = relationship("Event", secondary=watch_events, lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "watch_type IN ('persistent', 'dynamic')",
            name="watch_type_check",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'expired', 'promoted')",
            name="watch_status_check",
        ),
        CheckConstraint(
            "severity_threshold IN ('info', 'low', 'medium', 'high', 'critical')",
            name="watch_severity_check",
        ),
        Index("ix_watches_status", "status"),
        Index("ix_watches_plan_id", "plan_id"),
    )
