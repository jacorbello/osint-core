"""AuditLog model — immutable record of user and system actions."""

from typing import Any

from sqlalchemy import Index, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class AuditLog(UUIDMixin, TimestampMixin, Base):
    """Immutable audit trail entry."""

    __tablename__ = "audit_log"

    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_roles: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )

    __table_args__ = (
        Index("ix_audit_log_created_at_desc", text("created_at DESC")),
    )
