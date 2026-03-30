"""add reports table

Revision ID: 0009
Revises: dd493f3ccae5
Create Date: 2026-03-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "dd493f3ccae5"
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

    if not _table_exists(bind, "osint", "reports"):
        op.create_table(
            "reports",
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
            sa.Column("artifact_uri", sa.Text(), nullable=False),
            sa.Column(
                "generated_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("lead_count", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
            schema="osint",
        )

        op.create_index(
            "ix_reports_plan_id",
            "reports",
            ["plan_id"],
            schema="osint",
        )
        op.create_index(
            "ix_reports_generated_at",
            "reports",
            ["generated_at"],
            schema="osint",
        )


def downgrade() -> None:
    op.drop_index(
        "ix_reports_generated_at", table_name="reports", schema="osint"
    )
    op.drop_index(
        "ix_reports_plan_id", table_name="reports", schema="osint"
    )
    op.drop_table("reports", schema="osint")
