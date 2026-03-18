"""Brief model — AI-generated intelligence briefs."""

import uuid

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Brief(UUIDMixin, TimestampMixin, Base):
    """An AI-generated intelligence brief."""

    __tablename__ = "briefs"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    content_pdf_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_query: Mapped[str | None] = mapped_column(Text, nullable=True)

    event_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    entity_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )
    indicator_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}", nullable=False
    )

    generated_by: Mapped[str] = mapped_column(
        Text, default="vllm", server_default=sa.text("'vllm'")
    )
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osint.plan_versions.id"), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan_version = relationship("PlanVersion", lazy="selectin")
