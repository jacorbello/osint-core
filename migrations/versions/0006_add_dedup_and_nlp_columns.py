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


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        schema="osint",
    )
    op.add_column(
        "events",
        sa.Column(
            "canonical_event_id",
            sa.UUID(as_uuid=True),
            nullable=True,
        ),
        schema="osint",
    )
    op.create_foreign_key(
        "fk_events_canonical_event_id",
        "events",
        "events",
        ["canonical_event_id"],
        ["id"],
        source_schema="osint",
        referent_schema="osint",
    )
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
    op.add_column(
        "events",
        sa.Column("nlp_relevance", sa.Text(), nullable=True),
        schema="osint",
    )
    op.add_column(
        "events",
        sa.Column("nlp_summary", sa.Text(), nullable=True),
        schema="osint",
    )
    op.add_column(
        "events",
        sa.Column("fatalities", sa.Integer(), nullable=True),
        schema="osint",
    )
    op.create_index(
        "ix_events_simhash",
        "events",
        ["simhash"],
        schema="osint",
    )


def downgrade() -> None:
    op.drop_index("ix_events_simhash", table_name="events", schema="osint")
    op.drop_column("events", "fatalities", schema="osint")
    op.drop_column("events", "nlp_summary", schema="osint")
    op.drop_column("events", "nlp_relevance", schema="osint")
    op.drop_column("events", "corroboration_count", schema="osint")
    op.drop_constraint(
        "fk_events_canonical_event_id", "events", schema="osint"
    )
    op.drop_column("events", "canonical_event_id", schema="osint")
    op.drop_column("events", "simhash", schema="osint")
