"""add geographic columns to events

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(bind, schema: str, table: str, column: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_schema = :schema AND table_name = :table AND column_name = :column"
        ),
        {"schema": schema, "table": table, "column": column},
    )
    return result.fetchone() is not None


def _index_exists(bind, index: str, schema: str = "osint") -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND c.relkind = 'i' AND n.nspname = :schema"
        ),
        {"name": index, "schema": schema},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()

    cols = [
        ("latitude", sa.Column("latitude", sa.Float(), nullable=True)),
        ("longitude", sa.Column("longitude", sa.Float(), nullable=True)),
        ("country_code", sa.Column("country_code", sa.Text(), nullable=True)),
        ("region", sa.Column("region", sa.Text(), nullable=True)),
        ("source_category", sa.Column("source_category", sa.Text(), nullable=True)),
        ("actors", sa.Column("actors", postgresql.JSONB(), nullable=True)),
        ("event_subtype", sa.Column("event_subtype", sa.Text(), nullable=True)),
    ]
    for col_name, col_def in cols:
        if not _column_exists(bind, "osint", "events", col_name):
            op.add_column("events", col_def, schema="osint")

    if not _index_exists(bind, "ix_events_country_code"):
        op.create_index("ix_events_country_code", "events", ["country_code"], schema="osint")
    if not _index_exists(bind, "ix_events_region"):
        op.create_index("ix_events_region", "events", ["region"], schema="osint")
    if not _index_exists(bind, "ix_events_source_category"):
        op.create_index("ix_events_source_category", "events", ["source_category"], schema="osint")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS osint.ix_events_source_category")
    op.execute("DROP INDEX IF EXISTS osint.ix_events_region")
    op.execute("DROP INDEX IF EXISTS osint.ix_events_country_code")

    bind = op.get_bind()
    for col in ("event_subtype", "actors", "source_category", "region", "country_code", "longitude", "latitude"):
        if _column_exists(bind, "osint", "events", col):
            op.drop_column("events", col, schema="osint")
