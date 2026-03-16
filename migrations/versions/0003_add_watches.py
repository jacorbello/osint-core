"""add watches table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, schema: str, table: str) -> bool:
    return bind.dialect.has_table(bind, table, schema=schema)


def _index_exists(bind, index: str) -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND c.relkind = 'i'"
        ),
        {"name": index},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "osint", "watches"):
        op.create_table(
            "watches",
            sa.Column(
                "id", sa.UUID(), nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("name", sa.Text(), nullable=False, unique=True),
            sa.Column("watch_type", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
            sa.Column("region", sa.Text(), nullable=True),
            sa.Column("country_codes", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column("bounding_box", postgresql.JSONB(), nullable=True),
            sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column("source_filter", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column(
                "severity_threshold", sa.Text(),
                server_default=sa.text("'medium'"), nullable=False,
            ),
            sa.Column("plan_id", sa.Text(), nullable=True),
            sa.Column("ttl_hours", sa.Integer(), nullable=True),
            sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("promoted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("created_by", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_watches")),
            sa.CheckConstraint("watch_type IN ('persistent', 'dynamic')", name=op.f("ck_watches_watch_type_check")),
            sa.CheckConstraint("status IN ('active', 'paused', 'expired', 'promoted')", name=op.f("ck_watches_watch_status_check")),
            sa.CheckConstraint("severity_threshold IN ('info', 'low', 'medium', 'high', 'critical')", name=op.f("ck_watches_watch_severity_check")),
            schema="osint",
        )

    if not _index_exists(bind, "ix_watches_status"):
        op.create_index("ix_watches_status", "watches", ["status"], schema="osint")
    if not _index_exists(bind, "ix_watches_plan_id"):
        op.create_index("ix_watches_plan_id", "watches", ["plan_id"], schema="osint")

    if not _table_exists(bind, "osint", "watch_events"):
        op.create_table(
            "watch_events",
            sa.Column("watch_id", sa.UUID(), sa.ForeignKey("osint.watches.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("event_id", sa.UUID(), sa.ForeignKey("osint.events.id", ondelete="CASCADE"), primary_key=True),
            schema="osint",
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS osint.watch_events CASCADE")
    op.execute("DROP INDEX IF EXISTS osint.ix_watches_plan_id")
    op.execute("DROP INDEX IF EXISTS osint.ix_watches_status")
    op.execute("DROP TABLE IF EXISTS osint.watches CASCADE")
