"""merge migration heads

Revision ID: 77ec0a12abb2
Revises: 0003, 0006
Create Date: 2026-03-17 07:08:39.624618

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77ec0a12abb2'
down_revision: Union[str, None] = ('0003', '0006')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
