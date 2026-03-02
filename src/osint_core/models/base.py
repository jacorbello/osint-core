"""Base classes and mixins for all OSINT models."""

import uuid
from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Naming conventions for constraints — keeps Alembic migrations deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all OSINT models.

    All tables live in the ``osint`` Postgres schema.
    """

    metadata = MetaData(schema="osint", naming_convention=NAMING_CONVENTION)


class UUIDMixin:
    """Adds a UUID primary key column."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Adds a ``created_at`` column with server-side default."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
    )
