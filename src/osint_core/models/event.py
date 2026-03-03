"""Event model and association tables."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from osint_core.models.base import Base, TimestampMixin, UUIDMixin

# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------

event_entities = Table(
    "event_entities",
    Base.metadata,
    Column(
        "event_id", UUID(as_uuid=True),
        ForeignKey("osint.events.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "entity_id", UUID(as_uuid=True),
        ForeignKey("osint.entities.id", ondelete="CASCADE"), primary_key=True,
    ),
)

event_indicators = Table(
    "event_indicators",
    Base.metadata,
    Column(
        "event_id", UUID(as_uuid=True),
        ForeignKey("osint.events.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "indicator_id", UUID(as_uuid=True),
        ForeignKey("osint.indicators.id", ondelete="CASCADE"), primary_key=True,
    ),
)

event_artifacts = Table(
    "event_artifacts",
    Base.metadata,
    Column(
        "event_id", UUID(as_uuid=True),
        ForeignKey("osint.events.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "artifact_id", UUID(as_uuid=True),
        ForeignKey("osint.artifacts.id", ondelete="CASCADE"), primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


class Event(UUIDMixin, TimestampMixin, Base):
    """An ingested OSINT event."""

    __tablename__ = "events"

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    occurred_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)

    dedupe_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osint.plan_versions.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False
    )

    # FTS vector — the actual GENERATED ALWAYS AS expression is applied in the
    # Alembic migration.  We define the column here so SQLAlchemy knows about it.
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    # --- relationships ---
    plan_version = relationship("PlanVersion", lazy="selectin")
    entities = relationship("Entity", secondary=event_entities, lazy="selectin")
    indicators = relationship("Indicator", secondary=event_indicators, lazy="selectin")
    artifacts = relationship("Artifact", secondary=event_artifacts, lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="severity_check",
        ),
        Index("ix_events_dedupe_fingerprint", "dedupe_fingerprint", unique=True),
        Index("ix_events_source_id_ingested_at", "source_id", ingested_at.desc()),
        Index("ix_events_score_desc", score.desc().nullslast()),
        Index("ix_events_search_vector", "search_vector", postgresql_using="gin"),
    )
