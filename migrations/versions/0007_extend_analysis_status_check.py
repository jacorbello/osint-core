"""extend analysis_status check constraint with new statuses

Revision ID: 0007
Revises: 77ec0a12abb2
Create Date: 2026-04-02

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "77ec0a12abb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CONSTRAINT = "analysis_status IN ('pending', 'completed', 'no_source_material', 'failed')"
NEW_CONSTRAINT = (
    "analysis_status IN ("
    "'pending', 'completed', 'no_source_material', 'failed', "
    "'not_actionable', 'extraction_failed', 'non_english', 'no_content'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_leads_analysis_status_valid", "leads", schema="osint")
    op.create_check_constraint(
        "ck_leads_analysis_status_valid",
        "leads",
        NEW_CONSTRAINT,
        schema="osint",
    )


def downgrade() -> None:
    op.drop_constraint("ck_leads_analysis_status_valid", "leads", schema="osint")
    op.create_check_constraint(
        "ck_leads_analysis_status_valid",
        "leads",
        OLD_CONSTRAINT,
        schema="osint",
    )
