"""Tests for Pydantic v2 API schemas."""

import uuid
from datetime import UTC, datetime

from osint_core.schemas.alert import AlertAckRequest, AlertEscalateRequest, AlertResponse
from osint_core.schemas.audit import AuditLogResponse
from osint_core.schemas.brief import BriefGenerateRequest, BriefResponse
from osint_core.schemas.common import (
    JobStatusEnum,
    PaginatedResponse,
    RetentionClassEnum,
    SeverityEnum,
    StatusEnum,
)
from osint_core.schemas.entity import EntityResponse
from osint_core.schemas.event import EventResponse
from osint_core.schemas.indicator import IndicatorResponse
from osint_core.schemas.job import JobResponse
from osint_core.schemas.plan import PlanValidationResult, PlanVersionResponse
from osint_core.schemas.watch import (
    WatchCreateRequest,
    WatchResponse,
    WatchStatusEnum,
    WatchTypeEnum,
)


def test_event_response_schema():
    data = {
        "id": "00000000-0000-0000-0000-000000000001",
        "event_type": "cve_published",
        "source_id": "nvd_feeds_recent",
        "title": "CVE-2026-0001",
        "severity": "high",
        "score": 3.5,
        "dedupe_fingerprint": "abc123",
        "ingested_at": "2026-03-01T00:00:00Z",
        "metadata": {},
    }
    event = EventResponse.model_validate(data)
    assert event.event_type == "cve_published"
    assert event.score == 3.5
    assert event.severity == SeverityEnum.high


def test_plan_validation_result():
    result = PlanValidationResult(is_valid=True, errors=[], warnings=[])
    assert result.is_valid is True
    assert result.errors == []
    assert result.warnings == []
    assert result.diff_summary is None


def test_plan_validation_result_with_errors():
    result = PlanValidationResult(
        is_valid=False,
        errors=["missing required field: sources"],
        warnings=["retention_class 'ephemeral' has short TTL"],
        diff_summary="+2 sources, -1 filter",
    )
    assert result.is_valid is False
    assert len(result.errors) == 1
    assert result.diff_summary == "+2 sources, -1 filter"


def test_plan_version_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000010",
        "plan_id": "core-threat-feed",
        "version": 3,
        "content_hash": "sha256:abc123",
        "content": {"sources": ["nvd", "cisa"]},
        "retention_class": "standard",
        "is_active": True,
        "created_at": "2026-03-01T00:00:00Z",
    }
    plan = PlanVersionResponse.model_validate(data)
    assert plan.plan_id == "core-threat-feed"
    assert plan.version == 3
    assert plan.is_active is True
    assert plan.retention_class == RetentionClassEnum.standard


def test_indicator_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000002",
        "indicator_type": "ipv4",
        "value": "192.168.1.100",
        "confidence": 0.85,
        "first_seen": "2026-03-01T00:00:00Z",
        "last_seen": "2026-03-01T12:00:00Z",
        "sources": ["abuse-ch"],
        "metadata": {"asn": "AS12345"},
        "created_at": "2026-03-01T00:00:00Z",
    }
    indicator = IndicatorResponse.model_validate(data)
    assert indicator.indicator_type == "ipv4"
    assert indicator.confidence == 0.85
    assert indicator.sources == ["abuse-ch"]


def test_entity_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000003",
        "entity_type": "person",
        "name": "John Doe",
        "aliases": ["jdoe"],
        "attributes": {"country": "US"},
        "first_seen": "2026-03-01T00:00:00Z",
        "last_seen": "2026-03-01T00:00:00Z",
        "created_at": "2026-03-01T00:00:00Z",
    }
    entity = EntityResponse.model_validate(data)
    assert entity.name == "John Doe"
    assert entity.aliases == ["jdoe"]


def test_alert_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000004",
        "fingerprint": "alert-fp-001",
        "severity": "critical",
        "title": "Suspicious activity detected",
        "status": "open",
        "occurrences": 5,
        "first_fired_at": "2026-03-01T00:00:00Z",
        "last_fired_at": "2026-03-01T01:00:00Z",
        "created_at": "2026-03-01T00:00:00Z",
    }
    alert = AlertResponse.model_validate(data)
    assert alert.severity == SeverityEnum.critical
    assert alert.status == StatusEnum.open
    assert alert.occurrences == 5


def test_alert_ack_request():
    req = AlertAckRequest(acked_by="analyst-1")
    assert req.acked_by == "analyst-1"


def test_alert_escalate_request():
    req = AlertEscalateRequest(reason="Needs senior review", escalate_to="soc-lead")
    assert req.reason == "Needs senior review"
    assert req.escalate_to == "soc-lead"


def test_brief_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000005",
        "title": "Weekly Threat Summary",
        "content_md": "# Summary\n\nNo critical threats.",
        "generated_by": "llm",
        "model_id": "llama3.1:8b",
        "created_at": "2026-03-01T00:00:00Z",
    }
    brief = BriefResponse.model_validate(data)
    assert brief.title == "Weekly Threat Summary"
    assert brief.generated_by == "llm"


def test_brief_generate_request():
    req = BriefGenerateRequest(query="Summarize CVE activity in the last 24 hours")
    assert "CVE" in req.query


def test_job_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000006",
        "job_type": "ingest_nvd",
        "status": "succeeded",
        "retry_count": 0,
        "input_params": {"feed": "recent"},
        "output": {"events_created": 42},
        "created_at": "2026-03-01T00:00:00Z",
    }
    job = JobResponse.model_validate(data)
    assert job.job_type == "ingest_nvd"
    assert job.status == JobStatusEnum.succeeded
    assert job.output["events_created"] == 42


def test_audit_log_response():
    data = {
        "id": "00000000-0000-0000-0000-000000000007",
        "action": "alert.ack",
        "actor": "user-uuid-here",
        "actor_username": "analyst-1",
        "actor_roles": ["analyst"],
        "resource_type": "alert",
        "resource_id": "00000000-0000-0000-0000-000000000004",
        "details": {"previous_status": "open"},
        "created_at": "2026-03-01T00:00:00Z",
    }
    audit = AuditLogResponse.model_validate(data)
    assert audit.action == "alert.ack"
    assert audit.actor_username == "analyst-1"


def test_severity_enum_values():
    assert SeverityEnum.info == "info"
    assert SeverityEnum.low == "low"
    assert SeverityEnum.medium == "medium"
    assert SeverityEnum.high == "high"
    assert SeverityEnum.critical == "critical"


def test_status_enum_values():
    assert StatusEnum.open == "open"
    assert StatusEnum.acked == "acked"
    assert StatusEnum.escalated == "escalated"
    assert StatusEnum.resolved == "resolved"


def test_paginated_response():
    page = PaginatedResponse[str](
        items=["a", "b"], total=10, page=1, page_size=2, pages=5
    )
    assert len(page.items) == 2
    assert page.total == 10
    assert page.pages == 5


def test_event_response_includes_geo_fields():
    from osint_core.schemas.event import EventResponse

    event = EventResponse(
        id=uuid.uuid4(),
        event_type="conflict",
        source_id="gdelt_global",
        ingested_at=datetime.now(UTC),
        dedupe_fingerprint="abc123",
        latitude=48.38,
        longitude=31.17,
        country_code="UKR",
        region="Eastern Europe",
        source_category="military",
    )
    assert event.latitude == 48.38
    assert event.longitude == 31.17
    assert event.country_code == "UKR"
    assert event.region == "Eastern Europe"
    assert event.source_category == "military"


def test_watch_create_request():
    req = WatchCreateRequest(
        name="eastern-europe",
        region="Eastern Europe",
        country_codes=["UKR", "RUS", "BLR"],
        severity_threshold="low",
        keywords=["NATO", "Wagner"],
    )
    assert req.name == "eastern-europe"
    assert len(req.country_codes) == 3


def test_watch_response():
    resp = WatchResponse(
        id=uuid.uuid4(),
        name="eastern-europe",
        watch_type=WatchTypeEnum.dynamic,
        status=WatchStatusEnum.active,
        region="Eastern Europe",
        country_codes=["UKR", "RUS"],
        severity_threshold="low",
        created_at=datetime.now(UTC),
        created_by="manual",
    )
    assert resp.watch_type == "dynamic"
    assert resp.status == "active"
