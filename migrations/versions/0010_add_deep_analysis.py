"""add deep_analysis and analysis_status to leads

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("deep_analysis", postgresql.JSONB(), nullable=True),
        schema="osint",
    )
    op.add_column(
        "leads",
        sa.Column(
            "analysis_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        schema="osint",
    )
    op.create_check_constraint(
        op.f("ck_leads_analysis_status_valid"),
        "leads",
        "analysis_status IN ('pending', 'completed', 'no_source_material', 'failed')",
        schema="osint",
    )
    op.create_index(
        "ix_leads_analysis_status",
        "leads",
        ["analysis_status"],
        schema="osint",
    )


def downgrade() -> None:
    op.drop_index("ix_leads_analysis_status", table_name="leads", schema="osint")
    op.drop_constraint(
        op.f("ck_leads_analysis_status_valid"), "leads", schema="osint"
    )
    op.drop_column("leads", "analysis_status", schema="osint")
    op.drop_column("leads", "deep_analysis", schema="osint")
