"""Add dedup and NLP columns from PR #37

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-16

PR #37 added simhash, canonical_event_id, corroboration_count, nlp_relevance,
nlp_summary, and fatalities to the Event model but did not include a migration.
This revision adds the missing columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
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


def _constraint_exists(bind, schema: str, table: str, constraint: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints"
            " WHERE constraint_schema = :schema AND table_name = :table"
            " AND constraint_name = :constraint"
        ),
        {"schema": schema, "table": table, "constraint": constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()

    if not _column_exists(bind, "osint", "events", "simhash"):
        op.add_column(
            "events",
            sa.Column("simhash", sa.BigInteger(), nullable=True),
            schema="osint",
        )

    if not _column_exists(bind, "osint", "events", "canonical_event_id"):
        op.add_column(
            "events",
            sa.Column(
                "canonical_event_id",
                sa.UUID(as_uuid=True),
                nullable=True,
            ),
            schema="osint",
        )

    if not _constraint_exists(bind, "osint", "events", "fk_events_canonical_event_id"):
        op.create_foreign_key(
            "fk_events_canonical_event_id",
            "events",
            "events",
            ["canonical_event_id"],
            ["id"],
            source_schema="osint",
            referent_schema="osint",
        )

    if not _column_exists(bind, "osint", "events", "corroboration_count"):
        op.add_column(
            "events",
            sa.Column(
                "corroboration_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            schema="osint",
        )

    if not _column_exists(bind, "osint", "events", "nlp_relevance"):
        op.add_column(
            "events",
            sa.Column("nlp_relevance", sa.Text(), nullable=True),
            schema="osint",
        )

    if not _column_exists(bind, "osint", "events", "nlp_summary"):
        op.add_column(
            "events",
            sa.Column("nlp_summary", sa.Text(), nullable=True),
            schema="osint",
        )

    if not _column_exists(bind, "osint", "events", "fatalities"):
        op.add_column(
            "events",
            sa.Column("fatalities", sa.Integer(), nullable=True),
            schema="osint",
        )

    if not _index_exists(bind, "ix_events_simhash"):
        op.create_index(
            "ix_events_simhash",
            "events",
            ["simhash"],
            schema="osint",
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "ix_events_simhash"):
        op.drop_index("ix_events_simhash", table_name="events", schema="osint")

    for col in ("fatalities", "nlp_summary", "nlp_relevance", "corroboration_count"):
        if _column_exists(bind, "osint", "events", col):
            op.drop_column("events", col, schema="osint")

    if _constraint_exists(bind, "osint", "events", "fk_events_canonical_event_id"):
        op.drop_constraint("fk_events_canonical_event_id", "events", schema="osint")

    for col in ("canonical_event_id", "simhash"):
        if _column_exists(bind, "osint", "events", col):
            op.drop_column("events", col, schema="osint")
