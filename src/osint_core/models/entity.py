"""Entity model — people, organisations, infrastructure, etc."""

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Entity(UUIDMixin, TimestampMixin, Base):
    """A named entity extracted from OSINT events."""

    __tablename__ = "entities"

    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}", nullable=False
    )

    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_entities_name_fts",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
