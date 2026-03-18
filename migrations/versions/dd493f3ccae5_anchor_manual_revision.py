"""Anchor manually-stamped revision dd493f3ccae5

Revision ID: dd493f3ccae5
Revises: 77ec0a12abb2
Create Date: 2026-03-17

Root cause: the production database's alembic_version table was manually set to
dd493f3ccae5 (likely via a direct ALTER TABLE or manual stamp outside of
Alembic). This revision never existed in version control, so `alembic upgrade
head` failed with "Can't locate revision identified by 'dd493f3ccae5'".

Fix: introduce a stub migration that places dd493f3ccae5 in the chain
immediately after the current head (77ec0a12abb2). The production DB is already
stamped at dd493f3ccae5, so Alembic will see it as current and treat this
migration as already applied — no schema changes are made. Future migrations
should set down_revision to 'dd493f3ccae5'.
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd493f3ccae5"
down_revision: Union[str, None] = "77ec0a12abb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema changes. This revision exists solely to anchor the manually
    # stamped production revision into the migration chain.
    pass


def downgrade() -> None:
    pass
