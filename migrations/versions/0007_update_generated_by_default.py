"""Update briefs.generated_by default from ollama to vllm

Revision ID: 0007
Revises: 0005
Create Date: 2026-03-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "briefs",
        "generated_by",
        server_default=sa.text("'vllm'"),
        schema="osint",
    )


def downgrade() -> None:
    op.alter_column(
        "briefs",
        "generated_by",
        server_default=sa.text("'ollama'"),
        schema="osint",
    )
