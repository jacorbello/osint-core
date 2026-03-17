"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(bind, schema: str, table: str) -> bool:
    return sa.inspect(bind).has_table(table, schema=schema)


def _index_exists(bind, index: str, schema: str = "osint") -> bool:
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relname = :name AND c.relkind = 'i' AND n.nspname = :schema"
        ),
        {"name": index, "schema": schema},
    )
    return result.fetchone() is not None


def _upgrade_online() -> None:
    bind = op.get_bind()

    # Create the osint schema
    op.execute("CREATE SCHEMA IF NOT EXISTS osint")

    # --- plan_versions ---
    if not _table_exists(bind, "osint", "plan_versions"):
        op.create_table(
            "plan_versions",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("plan_id", sa.Text(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.Text(), nullable=False),
            sa.Column("content", postgresql.JSONB(), nullable=False),
            sa.Column("retention_class", sa.Text(), nullable=False),
            sa.Column("git_commit_sha", sa.Text(), nullable=True),
            sa.Column("activated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("activated_by", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("validation_result", postgresql.JSONB(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_versions")),
            sa.UniqueConstraint("plan_id", "version", name=op.f("uq_plan_versions_plan_id")),
            sa.CheckConstraint(
                "retention_class IN ('ephemeral', 'standard', 'evidentiary')",
                name=op.f("ck_plan_versions_retention_class_check"),
            ),
            schema="osint",
        )

    # --- entities ---
    if not _table_exists(bind, "osint", "entities"):
        op.create_table(
            "entities",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("entity_type", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column(
                "aliases",
                postgresql.ARRAY(sa.Text()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "attributes",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "first_seen",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "last_seen",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
            schema="osint",
        )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    if not _index_exists(bind, "ix_entities_name_fts"):
        op.create_index(
            "ix_entities_name_fts",
            "entities",
            ["name"],
            schema="osint",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        )

    # --- indicators ---
    if not _table_exists(bind, "osint", "indicators"):
        op.create_table(
            "indicators",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("indicator_type", sa.Text(), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), server_default=sa.text("0.5"), nullable=False),
            sa.Column(
                "first_seen",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "last_seen",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "sources",
                postgresql.ARRAY(sa.Text()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_indicators")),
            sa.UniqueConstraint(
                "indicator_type", "value", name=op.f("uq_indicators_indicator_type")
            ),
            schema="osint",
        )

    # --- artifacts ---
    if not _table_exists(bind, "osint", "artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("artifact_type", sa.Text(), nullable=False),
            sa.Column("minio_uri", sa.Text(), nullable=True),
            sa.Column("minio_version_id", sa.Text(), nullable=True),
            sa.Column("sha256", sa.Text(), nullable=True),
            sa.Column("capture_tool", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("final_url", sa.Text(), nullable=True),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column(
                "retention_class",
                sa.Text(),
                server_default=sa.text("'standard'"),
                nullable=False,
            ),
            sa.Column(
                "plan_version_id",
                sa.UUID(),
                sa.ForeignKey("osint.plan_versions.id"),
                nullable=True,
            ),
            sa.Column("case_id", sa.UUID(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
            schema="osint",
        )

    # --- events ---
    if not _table_exists(bind, "osint", "events"):
        op.create_table(
            "events",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("event_type", sa.Text(), nullable=False),
            sa.Column("source_id", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("raw_excerpt", sa.Text(), nullable=True),
            sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "ingested_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("severity", sa.Text(), nullable=True),
            sa.Column("dedupe_fingerprint", sa.Text(), nullable=False),
            sa.Column(
                "plan_version_id",
                sa.UUID(),
                sa.ForeignKey("osint.plan_versions.id"),
                nullable=True,
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
            sa.CheckConstraint(
                "severity IN ('info', 'low', 'medium', 'high', 'critical')",
                name=op.f("ck_events_severity_check"),
            ),
            schema="osint",
        )

    # Events indexes
    if not _index_exists(bind, "ix_events_dedupe_fingerprint"):
        op.create_index(
            "ix_events_dedupe_fingerprint",
            "events",
            ["dedupe_fingerprint"],
            schema="osint",
        )
    if not _index_exists(bind, "ix_events_source_id_ingested_at"):
        op.create_index(
            "ix_events_source_id_ingested_at",
            "events",
            ["source_id", sa.text("ingested_at DESC")],
            schema="osint",
        )
    if not _index_exists(bind, "ix_events_score_desc"):
        op.create_index(
            "ix_events_score_desc",
            "events",
            [sa.text("score DESC NULLS LAST")],
            schema="osint",
        )
    # FTS generated column — SQLAlchemy cannot model GENERATED ALWAYS AS directly,
    # so we convert the plain tsvector column into a stored generated column.
    # These statements are safe to re-run: the column type set and drop/re-add are
    # guarded by checking whether the column is already a generated column.
    # NOTE: The GIN index on search_vector is created AFTER the column is rebuilt
    # as a generated column, because DROP COLUMN implicitly drops the index and we
    # need to recreate it on the final generated column.
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_schema = 'osint' AND table_name = 'events'"
            " AND column_name = 'search_vector'"
            " AND is_generated = 'ALWAYS'"
        )
    )
    if result.fetchone() is None:
        op.execute(
            """
            ALTER TABLE osint.events
              ALTER COLUMN search_vector
              SET DATA TYPE tsvector
              USING to_tsvector('english',
                coalesce(title, '') || ' ' || coalesce(summary, '')
                || ' ' || coalesce(raw_excerpt, '')
              );
            """
        )
        op.execute(
            """
            ALTER TABLE osint.events
              DROP COLUMN search_vector;
            """
        )
        op.execute(
            """
            ALTER TABLE osint.events
              ADD COLUMN search_vector tsvector
              GENERATED ALWAYS AS (
                to_tsvector('english',
                  coalesce(title, '') || ' ' || coalesce(summary, '')
                  || ' ' || coalesce(raw_excerpt, '')
                )
              ) STORED;
            """
        )

    # GIN index on the (re)built generated column — must come after the column
    # drop/re-add above so we don't create the index on the pre-generated column
    # only to have it implicitly dropped when the column is recreated.
    if not _index_exists(bind, "ix_events_search_vector"):
        op.create_index(
            "ix_events_search_vector",
            "events",
            ["search_vector"],
            schema="osint",
            postgresql_using="gin",
        )

    # --- event_entities ---
    if not _table_exists(bind, "osint", "event_entities"):
        op.create_table(
            "event_entities",
            sa.Column(
                "event_id",
                sa.UUID(),
                sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "entity_id",
                sa.UUID(),
                sa.ForeignKey("osint.entities.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            schema="osint",
        )

    # --- event_indicators ---
    if not _table_exists(bind, "osint", "event_indicators"):
        op.create_table(
            "event_indicators",
            sa.Column(
                "event_id",
                sa.UUID(),
                sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "indicator_id",
                sa.UUID(),
                sa.ForeignKey("osint.indicators.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            schema="osint",
        )

    # --- event_artifacts ---
    if not _table_exists(bind, "osint", "event_artifacts"):
        op.create_table(
            "event_artifacts",
            sa.Column(
                "event_id",
                sa.UUID(),
                sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "artifact_id",
                sa.UUID(),
                sa.ForeignKey("osint.artifacts.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            schema="osint",
        )

    # --- alerts ---
    if not _table_exists(bind, "osint", "alerts"):
        op.create_table(
            "alerts",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("fingerprint", sa.Text(), nullable=False),
            sa.Column("severity", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "event_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "indicator_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "entity_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column("route_name", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Text(),
                server_default=sa.text("'open'"),
                nullable=False,
            ),
            sa.Column(
                "occurrences",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
            sa.Column(
                "first_fired_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "last_fired_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            ),
            sa.Column("acked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("acked_by", sa.Text(), nullable=True),
            sa.Column(
                "plan_version_id",
                sa.UUID(),
                sa.ForeignKey("osint.plan_versions.id"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
            sa.CheckConstraint(
                "status IN ('open', 'acked', 'escalated', 'resolved')",
                name=op.f("ck_alerts_status_check"),
            ),
            schema="osint",
        )

    if not _index_exists(bind, "ix_alerts_fingerprint_last_fired"):
        op.create_index(
            "ix_alerts_fingerprint_last_fired",
            "alerts",
            ["fingerprint", sa.text("last_fired_at DESC")],
            schema="osint",
        )

    # --- briefs ---
    if not _table_exists(bind, "osint", "briefs"):
        op.create_table(
            "briefs",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("content_md", sa.Text(), nullable=False),
            sa.Column("content_pdf_uri", sa.Text(), nullable=True),
            sa.Column("target_query", sa.Text(), nullable=True),
            sa.Column(
                "event_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "entity_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "indicator_ids",
                postgresql.ARRAY(sa.UUID()),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "generated_by",
                sa.Text(),
                server_default=sa.text("'vllm'"),
                nullable=False,
            ),
            sa.Column("model_id", sa.Text(), nullable=True),
            sa.Column(
                "plan_version_id",
                sa.UUID(),
                sa.ForeignKey("osint.plan_versions.id"),
                nullable=True,
            ),
            sa.Column("requested_by", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_briefs")),
            schema="osint",
        )

    # --- jobs ---
    if not _table_exists(bind, "osint", "jobs"):
        op.create_table(
            "jobs",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("job_type", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                server_default=sa.text("'queued'"),
                nullable=False,
            ),
            sa.Column("celery_task_id", sa.Text(), nullable=True),
            sa.Column("k8s_job_name", sa.Text(), nullable=True),
            sa.Column(
                "input_params",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column(
                "output",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "retry_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            ),
            sa.Column("next_retry_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("idempotency_key", sa.Text(), nullable=True),
            sa.Column(
                "plan_version_id",
                sa.UUID(),
                sa.ForeignKey("osint.plan_versions.id"),
                nullable=True,
            ),
            sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')",
                name=op.f("ck_jobs_status_check"),
            ),
            schema="osint",
        )

    if not _index_exists(bind, "ix_jobs_idempotency_key"):
        op.create_index(
            "ix_jobs_idempotency_key",
            "jobs",
            ["idempotency_key"],
            unique=True,
            schema="osint",
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )

    # --- audit_log ---
    if not _table_exists(bind, "osint", "audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("actor", sa.Text(), nullable=True),
            sa.Column("actor_username", sa.Text(), nullable=True),
            sa.Column("actor_roles", postgresql.ARRAY(sa.Text()), nullable=True),
            sa.Column("resource_type", sa.Text(), nullable=True),
            sa.Column("resource_id", sa.Text(), nullable=True),
            sa.Column(
                "details",
                postgresql.JSONB(),
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
            schema="osint",
        )

    if not _index_exists(bind, "ix_audit_log_created_at_desc"):
        op.create_index(
            "ix_audit_log_created_at_desc",
            "audit_log",
            [sa.text("created_at DESC")],
            schema="osint",
        )


def _upgrade_offline() -> None:
    """Emit unconditional DDL for ``alembic upgrade --sql`` mode."""
    op.execute("CREATE SCHEMA IF NOT EXISTS osint")

    op.create_table(
        "plan_versions",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("retention_class", sa.Text(), nullable=False),
        sa.Column("git_commit_sha", sa.Text(), nullable=True),
        sa.Column("activated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("validation_result", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_versions")),
        sa.UniqueConstraint("plan_id", "version", name=op.f("uq_plan_versions_plan_id")),
        sa.CheckConstraint(
            "retention_class IN ('ephemeral', 'standard', 'evidentiary')",
            name=op.f("ck_plan_versions_retention_class_check"),
        ),
        schema="osint",
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "aliases", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("attributes", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "first_seen", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "last_seen", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entities")),
        schema="osint",
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_entities_name_fts",
        "entities",
        ["name"],
        schema="osint",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    op.create_table(
        "indicators",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("indicator_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.5"), nullable=False),
        sa.Column(
            "first_seen", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "last_seen", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "sources", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_indicators")),
        sa.UniqueConstraint("indicator_type", "value", name=op.f("uq_indicators_indicator_type")),
        schema="osint",
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("minio_uri", sa.Text(), nullable=True),
        sa.Column("minio_version_id", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("capture_tool", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "retention_class", sa.Text(), server_default=sa.text("'standard'"), nullable=False
        ),
        sa.Column(
            "plan_version_id", sa.UUID(), sa.ForeignKey("osint.plan_versions.id"), nullable=True
        ),
        sa.Column("case_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        schema="osint",
    )

    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("raw_excerpt", sa.Text(), nullable=True),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "ingested_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("dedupe_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "plan_version_id", sa.UUID(), sa.ForeignKey("osint.plan_versions.id"), nullable=True
        ),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name=op.f("ck_events_severity_check"),
        ),
        schema="osint",
    )

    op.create_index(
        "ix_events_dedupe_fingerprint", "events", ["dedupe_fingerprint"], schema="osint"
    )
    op.create_index(
        "ix_events_source_id_ingested_at",
        "events",
        ["source_id", sa.text("ingested_at DESC")],
        schema="osint",
    )
    op.create_index(
        "ix_events_score_desc", "events", [sa.text("score DESC NULLS LAST")], schema="osint"
    )

    op.execute("""
        ALTER TABLE osint.events
          DROP COLUMN search_vector;
    """)
    op.execute("""
        ALTER TABLE osint.events
          ADD COLUMN search_vector tsvector
          GENERATED ALWAYS AS (
            to_tsvector('english',
              coalesce(title, '') || ' ' || coalesce(summary, '')
              || ' ' || coalesce(raw_excerpt, '')
            )
          ) STORED;
    """)
    op.create_index(
        "ix_events_search_vector",
        "events",
        ["search_vector"],
        schema="osint",
        postgresql_using="gin",
    )

    op.create_table(
        "event_entities",
        sa.Column(
            "event_id",
            sa.UUID(),
            sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id",
            sa.UUID(),
            sa.ForeignKey("osint.entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="osint",
    )
    op.create_table(
        "event_indicators",
        sa.Column(
            "event_id",
            sa.UUID(),
            sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "indicator_id",
            sa.UUID(),
            sa.ForeignKey("osint.indicators.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="osint",
    )
    op.create_table(
        "event_artifacts",
        sa.Column(
            "event_id",
            sa.UUID(),
            sa.ForeignKey("osint.events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "artifact_id",
            sa.UUID(),
            sa.ForeignKey("osint.artifacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="osint",
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "event_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "indicator_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "entity_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("route_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "first_fired_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "last_fired_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("acked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("acked_by", sa.Text(), nullable=True),
        sa.Column(
            "plan_version_id", sa.UUID(), sa.ForeignKey("osint.plan_versions.id"), nullable=True
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
        sa.CheckConstraint(
            "status IN ('open', 'acked', 'escalated', 'resolved')",
            name=op.f("ck_alerts_status_check"),
        ),
        schema="osint",
    )
    op.create_index(
        "ix_alerts_fingerprint_last_fired",
        "alerts",
        ["fingerprint", sa.text("last_fired_at DESC")],
        schema="osint",
    )

    op.create_table(
        "briefs",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("content_pdf_uri", sa.Text(), nullable=True),
        sa.Column("target_query", sa.Text(), nullable=True),
        sa.Column(
            "event_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "entity_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "indicator_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("generated_by", sa.Text(), server_default=sa.text("'vllm'"), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column(
            "plan_version_id", sa.UUID(), sa.ForeignKey("osint.plan_versions.id"), nullable=True
        ),
        sa.Column("requested_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_briefs")),
        schema="osint",
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column("k8s_job_name", sa.Text(), nullable=True),
        sa.Column(
            "input_params", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("output", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_retry_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "plan_version_id", sa.UUID(), sa.ForeignKey("osint.plan_versions.id"), nullable=True
        ),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')",
            name=op.f("ck_jobs_status_check"),
        ),
        schema="osint",
    )
    op.create_index(
        "ix_jobs_idempotency_key",
        "jobs",
        ["idempotency_key"],
        unique=True,
        schema="osint",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("actor_username", sa.Text(), nullable=True),
        sa.Column("actor_roles", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        schema="osint",
    )
    op.create_index(
        "ix_audit_log_created_at_desc",
        "audit_log",
        [sa.text("created_at DESC")],
        schema="osint",
    )


def upgrade() -> None:
    if context.is_offline_mode():
        _upgrade_offline()
    else:
        _upgrade_online()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS osint.audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.briefs CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.event_artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.event_indicators CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.event_entities CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.events CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.artifacts CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.indicators CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.entities CASCADE")
    op.execute("DROP TABLE IF EXISTS osint.plan_versions CASCADE")
    op.execute("DROP SCHEMA IF EXISTS osint CASCADE")
