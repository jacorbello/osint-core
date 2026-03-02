"""Verify all OSINT models register correctly with Base.metadata."""

from osint_core.models.alert import Alert
from osint_core.models.artifact import Artifact
from osint_core.models.audit import AuditLog
from osint_core.models.base import Base
from osint_core.models.brief import Brief
from osint_core.models.entity import Entity
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from osint_core.models.plan import PlanVersion


def test_all_models_registered():
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "osint.plan_versions",
        "osint.events",
        "osint.entities",
        "osint.indicators",
        "osint.artifacts",
        "osint.alerts",
        "osint.briefs",
        "osint.jobs",
        "osint.audit_log",
        "osint.event_entities",
        "osint.event_indicators",
        "osint.event_artifacts",
    }
    assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


def test_event_model_has_expected_columns():
    columns = {c.name for c in Event.__table__.columns}
    assert "dedupe_fingerprint" in columns
    assert "score" in columns
    assert "severity" in columns
    assert "source_id" in columns


def test_plan_version_model_has_expected_columns():
    columns = {c.name for c in PlanVersion.__table__.columns}
    assert "plan_id" in columns
    assert "version" in columns
    assert "content_hash" in columns
    assert "retention_class" in columns
    assert "is_active" in columns


def test_entity_model_has_expected_columns():
    columns = {c.name for c in Entity.__table__.columns}
    assert "entity_type" in columns
    assert "name" in columns
    assert "aliases" in columns


def test_indicator_model_has_expected_columns():
    columns = {c.name for c in Indicator.__table__.columns}
    assert "indicator_type" in columns
    assert "value" in columns
    assert "confidence" in columns


def test_artifact_model_has_expected_columns():
    columns = {c.name for c in Artifact.__table__.columns}
    assert "artifact_type" in columns
    assert "sha256" in columns
    assert "minio_uri" in columns


def test_alert_model_has_expected_columns():
    columns = {c.name for c in Alert.__table__.columns}
    assert "fingerprint" in columns
    assert "severity" in columns
    assert "status" in columns
    assert "occurrences" in columns


def test_brief_model_has_expected_columns():
    columns = {c.name for c in Brief.__table__.columns}
    assert "title" in columns
    assert "content_md" in columns
    assert "generated_by" in columns


def test_job_model_has_expected_columns():
    columns = {c.name for c in Job.__table__.columns}
    assert "job_type" in columns
    assert "status" in columns
    assert "idempotency_key" in columns
    assert "retry_count" in columns


def test_audit_log_model_has_expected_columns():
    columns = {c.name for c in AuditLog.__table__.columns}
    assert "action" in columns
    assert "actor" in columns
    assert "details" in columns
    assert "resource_type" in columns


def test_all_models_use_osint_schema():
    """Every table should live in the 'osint' schema."""
    for table_name in Base.metadata.tables:
        assert table_name.startswith("osint."), f"Table {table_name} not in osint schema"
