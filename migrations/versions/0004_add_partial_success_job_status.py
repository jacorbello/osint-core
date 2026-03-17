"""add partial_success to job status check

Revision ID: 0004
Revises: 0001
Create Date: 2026-03-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_status_check"), "jobs", schema="osint")
    op.create_check_constraint(
        op.f("ck_jobs_status_check"),
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'partial_success', 'dead_letter')",
        schema="osint",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_jobs_status_check"), "jobs", schema="osint")
    op.create_check_constraint(
        op.f("ck_jobs_status_check"),
        "jobs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')",
        schema="osint",
    )
