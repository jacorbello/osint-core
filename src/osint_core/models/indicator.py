"""Indicator model — IOCs, observables, and threat indicators."""

from datetime import datetime
from typing import Any

from sqlalchemy import Float, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from osint_core.models.base import Base, TimestampMixin, UUIDMixin


class Indicator(UUIDMixin, TimestampMixin, Base):
    """A threat indicator (IP, domain, hash, etc.)."""

    __tablename__ = "indicators"

    indicator_type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")

    first_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    sources: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default="{}", nullable=False
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default="{}", nullable=False
    )

    __table_args__ = (
        UniqueConstraint("indicator_type", "value"),
    )
