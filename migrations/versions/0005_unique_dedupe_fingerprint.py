"""make dedupe_fingerprint index unique

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_events_dedupe_fingerprint", table_name="events", schema="osint")
    op.create_index(
        "ix_events_dedupe_fingerprint",
        "events",
        ["dedupe_fingerprint"],
        unique=True,
        schema="osint",
    )


def downgrade() -> None:
    op.drop_index("ix_events_dedupe_fingerprint", table_name="events", schema="osint")
    op.create_index(
        "ix_events_dedupe_fingerprint",
        "events",
        ["dedupe_fingerprint"],
        unique=False,
        schema="osint",
    )
