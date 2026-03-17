"""Tests for API schemas."""

import uuid
from datetime import UTC, datetime

from osint_core.schemas.alert import AlertResponse, AlertUpdateRequest
from osint_core.schemas.brief import BriefCreateRequest, BriefResponse
from osint_core.schemas.common import (
    CollectionResponse,
    JobStatusEnum,
    ProblemDetails,
    RetentionClassEnum,
    SeverityEnum,
    StatusEnum,
)
from osint_core.schemas.event import EventResponse
from osint_core.schemas.indicator import IndicatorResponse
from osint_core.schemas.job import JobCreateRequest, JobKindEnum, JobResponse
from osint_core.schemas.plan import (
    PlanActivationRequest,
    PlanValidationResult,
    PlanVersionResponse,
)


def test_event_response_schema():
    event = EventResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "event_type": "cve_published",
            "source_id": "nvd_feeds_recent",
            "severity": "high",
            "score": 3.5,
            "dedupe_fingerprint": "abc123",
            "ingested_at": "2026-03-01T00:00:00Z",
            "metadata": {},
        }
    )
    assert event.severity == SeverityEnum.high


def test_indicator_response_aliases_metadata():
    indicator = IndicatorResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "indicator_type": "ipv4",
            "value": "192.168.1.100",
            "confidence": 0.85,
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-03-01T12:00:00Z",
            "metadata_": {"asn": "AS12345"},
            "created_at": "2026-03-01T00:00:00Z",
        }
    )
    assert indicator.metadata == {"asn": "AS12345"}


def test_alert_update_request():
    req = AlertUpdateRequest(status="acked")
    assert req.status == StatusEnum.acked


def test_brief_create_request():
    req = BriefCreateRequest(query="Summarize CVE activity in the last 24 hours")
    assert "CVE" in req.query


def test_brief_response_defaults():
    brief = BriefResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000005",
            "title": "Weekly Threat Summary",
            "content_md": "# Summary\n\nNo critical threats.",
            "generated_by": "ollama",
            "created_at": "2026-03-01T00:00:00Z",
        }
    )
    assert brief.event_ids == []


def test_job_response_aliases():
    job = JobResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000006",
            "job_type": "ingest",
            "status": "partial_success",
            "input_params": {"feed": "recent"},
            "output": {"events_created": 42},
            "retry_count": 0,
            "created_at": "2026-03-01T00:00:00Z",
        }
    )
    assert job.kind == "ingest"
    assert job.status == JobStatusEnum.partial_success
    assert job.result["events_created"] == 42


def test_job_create_request():
    req = JobCreateRequest(kind=JobKindEnum.rescore, input={"plan_id": "core-threat"})
    assert req.kind == JobKindEnum.rescore


def test_problem_details_schema():
    problem = ProblemDetails(
        title="Not Found",
        status=404,
        code="not_found",
        detail="Event not found",
        instance="/api/v1/events/123",
        request_id="req-1",
    )
    assert problem.code == "not_found"


def test_collection_response_schema():
    class ExampleCollection(CollectionResponse):
        items: list[str]

    page = ExampleCollection(items=["a", "b"], page={"offset": 0, "limit": 2, "total": 10, "has_more": True})
    assert page.page.total == 10
    assert page.page.has_more is True


def test_plan_validation_result():
    result = PlanValidationResult(is_valid=True, errors=[], warnings=[])
    assert result.is_valid is True


def test_plan_activation_request_requires_action():
    request = PlanActivationRequest(version_id=uuid.uuid4())
    assert request.rollback is False


def test_plan_version_response():
    plan = PlanVersionResponse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "plan_id": "core-threat-feed",
            "version": 3,
            "content_hash": "sha256:abc123",
            "content": {"sources": ["nvd", "cisa"]},
            "retention_class": "standard",
            "is_active": True,
            "created_at": "2026-03-01T00:00:00Z",
        }
    )
    assert plan.retention_class == RetentionClassEnum.standard


def test_alert_response():
    alert = AlertResponse.model_validate(
        {
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
    )
    assert alert.status == StatusEnum.open


def test_event_response_includes_geo_fields():
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
    assert event.region == "Eastern Europe"
