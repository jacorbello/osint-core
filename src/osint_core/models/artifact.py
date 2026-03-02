"""Artifact model — captured files, screenshots, web archives."""

import uuid

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Artifact(UUIDMixin, TimestampMixin, Base):
    """A stored artifact (screenshot, HTML snapshot, PDF, etc.)."""

    __tablename__ = "artifacts"

    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    minio_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    minio_version_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_tool: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)

    retention_class: Mapped[str] = mapped_column(
        Text, default="standard", server_default="standard"
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osint.plan_versions.id"), nullable=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    plan_version = relationship("PlanVersion", lazy="selectin")
