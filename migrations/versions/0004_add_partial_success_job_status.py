"""add partial_success to job status check

Revision ID: 0004
Revises: 0001
Create Date: 2026-03-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_jobs_status_check", "jobs", schema="osint")
    op.create_check_constraint(
        "ck_jobs_status_check",
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')",
        schema="osint",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_status_check", "jobs", schema="osint")
    op.create_check_constraint(
        "ck_jobs_status_check",
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')",
        schema="osint",
    )
