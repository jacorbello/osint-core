"""add partial_success to job status check

Revision ID: 0004
Revises: 0001
Create Date: 2026-03-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_CONSTRAINT = "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')"
_OLD_CONSTRAINT = "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')"


def _constraint_exists(
    bind, schema: str, table: str, constraint: str, *, assume: bool = False
) -> bool:
    if bind is None:  # offline mode
        return assume
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints"
            " WHERE constraint_schema = :schema AND table_name = :table"
            " AND constraint_name = :constraint AND constraint_type = 'CHECK'"
        ),
        {"schema": schema, "table": table, "constraint": constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    constraint_name = op.f("ck_jobs_status_check")

    # Drop the old constraint only if it exists
    if _constraint_exists(bind, "osint", "jobs", constraint_name):
        op.drop_constraint(constraint_name, "jobs", schema="osint")

    # Add the new constraint only if it doesn't already exist
    if not _constraint_exists(bind, "osint", "jobs", constraint_name):
        op.create_check_constraint(
            constraint_name,
            "jobs",
            _NEW_CONSTRAINT,
            schema="osint",
        )


def downgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    constraint_name = op.f("ck_jobs_status_check")

    if _constraint_exists(bind, "osint", "jobs", constraint_name, assume=True):
        op.drop_constraint(constraint_name, "jobs", schema="osint")

    if not _constraint_exists(bind, "osint", "jobs", constraint_name):
        op.create_check_constraint(
            constraint_name,
            "jobs",
            _OLD_CONSTRAINT,
            schema="osint",
        )
