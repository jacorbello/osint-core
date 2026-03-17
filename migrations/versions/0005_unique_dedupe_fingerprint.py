"""make dedupe_fingerprint index unique

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(bind, index: str, schema: str = "osint") -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND c.relkind = 'i' AND n.nspname = :schema"
        ),
        {"name": index, "schema": schema},
    )
    return result.fetchone() is not None


def _index_is_unique(bind, index: str, schema: str = "osint") -> bool:
    result = bind.execute(
        sa.text(
            "SELECT i.indisunique"
            " FROM pg_index i"
            " JOIN pg_class c ON c.oid = i.indexrelid"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND c.relkind = 'i' AND n.nspname = :schema"
        ),
        {"name": index, "schema": schema},
    )
    row = result.fetchone()
    return row is not None and row[0]


def _upgrade_online() -> None:
    bind = op.get_bind()

    # Drop only if the existing index is non-unique (safe to skip if already unique)
    if _index_exists(bind, "ix_events_dedupe_fingerprint") and not _index_is_unique(
        bind, "ix_events_dedupe_fingerprint"
    ):
        op.drop_index("ix_events_dedupe_fingerprint", table_name="events", schema="osint")

    if not _index_exists(bind, "ix_events_dedupe_fingerprint"):
        op.create_index(
            "ix_events_dedupe_fingerprint",
            "events",
            ["dedupe_fingerprint"],
            unique=True,
            schema="osint",
        )


def _upgrade_offline() -> None:
    """Emit unconditional DDL for ``alembic upgrade --sql`` mode."""
    op.execute("DROP INDEX IF EXISTS osint.ix_events_dedupe_fingerprint")
    op.create_index(
        "ix_events_dedupe_fingerprint",
        "events",
        ["dedupe_fingerprint"],
        unique=True,
        schema="osint",
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _upgrade_offline()
    else:
        _upgrade_online()


def downgrade() -> None:
    bind = op.get_bind()

    # Drop only if the existing index is unique
    if _index_exists(bind, "ix_events_dedupe_fingerprint") and _index_is_unique(
        bind, "ix_events_dedupe_fingerprint"
    ):
        op.drop_index("ix_events_dedupe_fingerprint", table_name="events", schema="osint")

    if not _index_exists(bind, "ix_events_dedupe_fingerprint"):
        op.create_index(
            "ix_events_dedupe_fingerprint",
            "events",
            ["dedupe_fingerprint"],
            unique=False,
            schema="osint",
        )
