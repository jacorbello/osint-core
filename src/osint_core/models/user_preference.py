"""UserPreference model — per-user settings and saved searches."""

from datetime import datetime

from sqlalchemy import Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class UserPreference(UUIDMixin, TimestampMixin, Base):
    """Per-user preferences keyed by Keycloak ``sub`` claim."""

    __tablename__ = "user_preferences"

    user_sub: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    notification_prefs: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )
    saved_searches: Mapped[list] = mapped_column(
        JSONB, server_default="[]", nullable=False
    )
    timezone: Mapped[str] = mapped_column(
        Text, server_default="UTC", nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index("ix_user_preferences_user_sub", "user_sub", unique=True),
    )
