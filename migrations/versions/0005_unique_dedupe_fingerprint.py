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


def _index_exists(
    bind, index: str, schema: str = "osint", *, assume: bool = False
) -> bool:
    if bind is None:  # offline mode
        return assume
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND n.nspname = :schema AND c.relkind = 'i'"
        ),
        {"name": index, "schema": schema},
    )
    return result.fetchone() is not None


def _index_is_unique(bind, index: str, *, assume: bool = False) -> bool:
    if bind is None:  # offline mode
        return assume
    result = bind.execute(
        sa.text("SELECT indisunique FROM pg_index WHERE indexrelid = :name::regclass"),
        {"name": f"osint.{index}"},
    )
    row = result.fetchone()
    return row is not None and row[0]


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()

    # Drop only if the existing index is non-unique (safe to skip if already unique)
    idx = "ix_events_dedupe_fingerprint"
    if _index_exists(bind, idx) and not _index_is_unique(bind, idx):
        op.drop_index(idx, table_name="events", schema="osint")

    if not _index_exists(bind, idx):
        op.create_index(
            "ix_events_dedupe_fingerprint",
            "events",
            ["dedupe_fingerprint"],
            unique=True,
            schema="osint",
        )


def downgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()

    # Drop only if the existing index is unique
    idx = "ix_events_dedupe_fingerprint"
    if (
        _index_exists(bind, idx, assume=True)
        and _index_is_unique(bind, idx, assume=True)
    ):
        op.drop_index(idx, table_name="events", schema="osint")

    if not _index_exists(bind, "ix_events_dedupe_fingerprint"):
        op.create_index(
            "ix_events_dedupe_fingerprint",
            "events",
            ["dedupe_fingerprint"],
            unique=False,
            schema="osint",
        )
