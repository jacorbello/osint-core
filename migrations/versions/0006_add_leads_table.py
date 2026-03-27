"""add leads table

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(
    bind, schema: str, table: str, *, assume: bool = False
) -> bool:
    if bind is None:  # offline mode — no connection available
        return assume
    return bind.dialect.has_table(bind, table, schema=schema)


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()

    if not _table_exists(bind, "osint", "leads"):
        op.create_table(
            "leads",
            sa.Column(
                "id",
                sa.UUID(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("lead_type", sa.Text(), nullable=False),
            sa.Column(
                "status", sa.Text(), nullable=False, server_default="new"
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "constitutional_basis",
                postgresql.ARRAY(sa.Text()),
                server_default="{}",
                nullable=False,
            ),
            sa.Column("jurisdiction", sa.Text(), nullable=True),
            sa.Column("institution", sa.Text(), nullable=True),
            sa.Column("severity", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("dedupe_fingerprint", sa.Text(), nullable=False),
            sa.Column("plan_id", sa.Text(), nullable=True),
            sa.Column(
                "event_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default="{}",
                nullable=False,
            ),
            sa.Column(
                "entity_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default="{}",
                nullable=False,
            ),
            sa.Column("citations", postgresql.JSONB(), nullable=True),
            sa.Column("report_id", sa.UUID(), nullable=True),
            sa.Column(
                "first_surfaced_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "last_updated_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "reported_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
            sa.CheckConstraint(
                "lead_type IN ('incident', 'policy')",
                name=op.f("ck_leads_lead_type_check"),
            ),
            sa.CheckConstraint(
                "status IN ('new', 'reviewing', 'qualified', 'contacted', "
                "'retained', 'declined', 'stale')",
                name=op.f("ck_leads_lead_status_check"),
            ),
            sa.CheckConstraint(
                "severity IN ('info', 'low', 'medium', 'high', 'critical')",
                name=op.f("ck_leads_lead_severity_check"),
            ),
            sa.CheckConstraint(
                "confidence >= 0.0 AND confidence <= 1.0",
                name=op.f("ck_leads_lead_confidence_range"),
            ),
            schema="osint",
        )

        op.create_index(
            "ix_leads_dedupe_fingerprint",
            "leads",
            ["dedupe_fingerprint"],
            unique=True,
            schema="osint",
        )
        op.create_index(
            "ix_leads_status",
            "leads",
            ["status"],
            schema="osint",
        )
        op.create_index(
            "ix_leads_jurisdiction",
            "leads",
            ["jurisdiction"],
            schema="osint",
        )
        op.create_index(
            "ix_leads_reported_at",
            "leads",
            ["reported_at"],
            schema="osint",
        )
        op.create_index(
            "ix_leads_plan_id",
            "leads",
            ["plan_id"],
            schema="osint",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_leads_plan_id", table_name="leads", schema="osint"
    )
    op.drop_index(
        "ix_leads_reported_at", table_name="leads", schema="osint"
    )
    op.drop_index(
        "ix_leads_jurisdiction", table_name="leads", schema="osint"
    )
    op.drop_index(
        "ix_leads_status", table_name="leads", schema="osint"
    )
    op.drop_index(
        "ix_leads_dedupe_fingerprint", table_name="leads", schema="osint"
    )
    op.drop_table("leads", schema="osint")
