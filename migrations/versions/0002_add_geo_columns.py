"""add geographic columns to events

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-03
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("latitude", sa.Float(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("longitude", sa.Float(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("country_code", sa.Text(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("region", sa.Text(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("source_category", sa.Text(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("actors", postgresql.JSONB(), nullable=True), schema="osint")
    op.add_column("events", sa.Column("event_subtype", sa.Text(), nullable=True), schema="osint")
    op.create_index("ix_events_country_code", "events", ["country_code"], schema="osint")
    op.create_index("ix_events_region", "events", ["region"], schema="osint")
    op.create_index("ix_events_source_category", "events", ["source_category"], schema="osint")


def downgrade() -> None:
    op.drop_index("ix_events_source_category", table_name="events", schema="osint")
    op.drop_index("ix_events_region", table_name="events", schema="osint")
    op.drop_index("ix_events_country_code", table_name="events", schema="osint")
    op.drop_column("events", "event_subtype", schema="osint")
    op.drop_column("events", "actors", schema="osint")
    op.drop_column("events", "source_category", schema="osint")
    op.drop_column("events", "region", schema="osint")
    op.drop_column("events", "country_code", schema="osint")
    op.drop_column("events", "longitude", schema="osint")
    op.drop_column("events", "latitude", schema="osint")
