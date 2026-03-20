"""Add user_preferences table

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_sub", sa.Text(), nullable=False),
        sa.Column("notification_prefs", JSONB(), server_default="{}", nullable=False),
        sa.Column("saved_searches", JSONB(), server_default="[]", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_preferences")),
        sa.UniqueConstraint("user_sub", name=op.f("uq_user_preferences_user_sub")),
        schema="osint",
    )
    op.create_index(
        op.f("ix_user_preferences_user_sub"),
        "user_preferences",
        ["user_sub"],
        unique=True,
        schema="osint",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_user_preferences_user_sub"),
        table_name="user_preferences",
        schema="osint",
    )
    op.drop_table("user_preferences", schema="osint")
