"""Job model — tracked Celery / K8s jobs."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column, relationship

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Job(UUIDMixin, TimestampMixin, Base):
    """A tracked background job (Celery task or K8s Job)."""

    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, default="queued", server_default="queued"
    )

    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    k8s_job_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    output: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    next_retry_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("osint.plan_versions.id"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    plan_version = relationship("PlanVersion", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')",
            name="status_check",
        ),
        Index(
            "ix_jobs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )
