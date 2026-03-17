"""Route unit tests without HTTP client transport."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response

from osint_core.api.routes import alerts, audit, briefs, entities, events, indicators, jobs, search
from osint_core.main import app
from osint_core.models.alert import Alert
from osint_core.models.audit import AuditLog
from osint_core.models.brief import Brief
from osint_core.models.entity import Entity
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from tests.helpers import make_request, make_user, run_async


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _mock_scalars_result(items: list, total: int | None = None):
    if total is None:
        total = len(items)
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    data_result = MagicMock()
    data_result.scalars.return_value = scalars_mock
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    return [data_result, count_result]


def _mock_single_result(item):
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    return result


def _make_event(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "event_type": "vulnerability",
        "source_id": "cisa_kev",
        "title": "Test Event",
        "summary": "A test event",
        "severity": "high",
        "score": 7.5,
        "dedupe_fingerprint": "abc123",
        "metadata_": {},
        "occurred_at": now,
        "ingested_at": now,
        "created_at": now,
        "raw_excerpt": None,
        "plan_version_id": None,
        "latitude": None,
        "longitude": None,
        "country_code": None,
        "region": None,
        "source_category": None,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Event)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_indicator(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "indicator_type": "ipv4",
        "value": "192.168.1.1",
        "confidence": 0.9,
        "sources": ["cisa_kev"],
        "metadata_": {"asn": "AS1"},
        "first_seen": now,
        "last_seen": now,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Indicator)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_entity(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "entity_type": "organization",
        "name": "Test Corp",
        "aliases": [],
        "attributes": {},
        "first_seen": now,
        "last_seen": now,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Entity)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_alert(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "fingerprint": "fp-123",
        "severity": "high",
        "title": "Test Alert",
        "summary": "Alert summary",
        "status": "open",
        "occurrences": 1,
        "event_ids": [],
        "indicator_ids": [],
        "entity_ids": [],
        "route_name": None,
        "first_fired_at": now,
        "last_fired_at": now,
        "acked_at": None,
        "acked_by": None,
        "plan_version_id": None,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Alert)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_brief(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test Brief",
        "content_md": "# Brief",
        "content_pdf_uri": None,
        "target_query": None,
        "generated_by": "ollama",
        "model_id": None,
        "event_ids": [],
        "entity_ids": [],
        "indicator_ids": [],
        "plan_version_id": None,
        "requested_by": "admin",
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Brief)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_job(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "job_type": "ingest",
        "status": "queued",
        "celery_task_id": None,
        "k8s_job_name": None,
        "input_params": {},
        "output": {},
        "error": None,
        "retry_count": 0,
        "next_retry_at": None,
        "idempotency_key": None,
        "plan_version_id": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Job)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _make_audit(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "action": "event.created",
        "actor": "user-1",
        "actor_username": "admin",
        "actor_roles": ["admin"],
        "resource_type": "event",
        "resource_id": str(uuid.uuid4()),
        "details": {},
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=AuditLog)
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def test_list_events_uses_page_envelope():
    db = _mock_db()
    db.execute = AsyncMock(side_effect=_mock_scalars_result([_make_event()], 1))
    result = run_async(events.list_events(limit=10, offset=0, sort=None, db=db, current_user=make_user()))
    assert result.page.total == 1
    assert result.items[0].title == "Test Event"


def test_get_event_not_found_returns_problem_payload():
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(None))
    response = run_async(
        events.get_event(
            uuid.uuid4(),
            request=make_request("/api/v1/events/missing"),
            db=db,
            current_user=make_user(),
        )
    )
    assert response.status_code == 404
    assert json.loads(response.body)["code"] == "not_found"


def test_get_indicator_uses_metadata_alias():
    db = _mock_db()
    indicator = _make_indicator()
    indicator.metadata = indicator.metadata_
    db.execute = AsyncMock(return_value=_mock_single_result(indicator))
    result = run_async(
        indicators.get_indicator(
            uuid.uuid4(),
            request=make_request("/api/v1/indicators/1"),
            db=db,
            current_user=make_user(),
        )
    )
    assert result.metadata == {"asn": "AS1"}


def test_get_entity_found():
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(_make_entity()))
    result = run_async(
        entities.get_entity(
            uuid.uuid4(),
            request=make_request("/api/v1/entities/1"),
            db=db,
            current_user=make_user(),
        )
    )
    assert result.name == "Test Corp"


def test_patch_alert_acks_with_current_user():
    alert = _make_alert(status="open")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(alert))
    db.refresh = AsyncMock()
    result = run_async(
        alerts.update_alert(
            alert.id,
            body=alerts.AlertUpdateRequest(status="acked"),
            request=make_request(f"/api/v1/alerts/{alert.id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )
    assert result.acked_by == "admin"
    assert result.status == "acked"


def test_patch_alert_rejects_invalid_transition():
    alert = _make_alert(status="open")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(alert))
    response = run_async(
        alerts.update_alert(
            alert.id,
            body=alerts.AlertUpdateRequest(status="resolved"),
            request=make_request(f"/api/v1/alerts/{alert.id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )
    assert response.status_code == 409
    assert json.loads(response.body)["code"] == "invalid_state_transition"


def test_create_brief_returns_201_and_location():
    brief = _make_brief(title="Latest CVE threats", target_query="Latest CVE threats")
    db = _mock_db()
    response = Response()

    with patch("osint_core.api.routes.briefs.BriefGenerator") as generator_cls:
        generator = AsyncMock()
        generator.generate = AsyncMock(return_value="# Brief\nGenerated content.")
        generator_cls.return_value = generator
        with patch("osint_core.api.routes.briefs.Brief", return_value=brief):
            result = run_async(
                briefs.create_brief(
                    body=briefs.BriefCreateRequest(query="Latest CVE threats"),
                    request=make_request("/api/v1/briefs", method="POST"),
                    response=response,
                    db=db,
                    current_user=make_user(),
                )
            )
    assert response.headers["Location"].endswith(str(brief.id))
    assert result.title == "Latest CVE threats"


def test_search_events_new_path_behavior():
    db = _mock_db()
    db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
    result = run_async(
        search.search_events(
            q="ransomware",
            limit=10,
            offset=0,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.retrieval_mode == "lexical"


def test_create_ingest_job():
    db = _mock_db()
    response = Response()
    job = _make_job(job_type="ingest", celery_task_id="task-abc-123")

    async def refresh(target):
        for key, value in {
            "id": job.id,
            "job_type": "ingest",
            "status": "queued",
            "celery_task_id": "task-abc-123",
            "input_params": {"source_id": "cisa_kev", "plan_id": "test-plan"},
            "output": {},
            "retry_count": 0,
            "created_at": job.created_at,
        }.items():
            setattr(target, key, value)

    db.refresh = refresh

    with patch("osint_core.api.routes.jobs.ingest_source") as mock_ingest:
        mock_ingest.delay.return_value = MagicMock(id="task-abc-123")
        job_result = run_async(
            jobs.create_job(
                body=jobs.JobCreateRequest(
                    kind="ingest",
                    input={"source_id": "cisa_kev", "plan_id": "test-plan"},
                ),
                request=make_request("/api/v1/jobs", method="POST"),
                response=response,
                db=db,
                current_user=make_user(),
            )
        )

    assert response.headers["Location"].endswith(str(job.id))
    assert jobs.JobResponse.model_validate(job_result).kind == "ingest"


def test_create_job_requires_input_fields():
    db = _mock_db()
    response = Response()
    result = run_async(
        jobs.create_job(
            body=jobs.JobCreateRequest(kind="ingest", input={"source_id": "cisa_kev"}),
            request=make_request("/api/v1/jobs", method="POST"),
            response=response,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.status_code == 422
    assert json.loads(result.body)["code"] == "validation_failed"


def test_list_audit_entries():
    with patch("osint_core.api.routes.audit.list_audit_entries", AsyncMock(return_value=([_make_audit()], 1))):
        result = run_async(audit.list_audit(limit=10, offset=0, action=None, db=_mock_db(), current_user=make_user()))
    assert result.page.total == 1


def test_openapi_schema_loads():
    schema = app.openapi()
    assert "/api/v1/jobs" in schema["paths"]
    assert "/api/v1/plans" in schema["paths"]
    assert "ProblemDetails" in schema["components"]["schemas"]
    assert schema["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"
    assert schema["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert {"BearerAuth": []} in schema["paths"]["/api/v1/jobs"]["get"]["security"]
    kind_parameter = next(
        parameter
        for parameter in schema["paths"]["/api/v1/jobs"]["get"]["parameters"]
        if parameter["name"] == "kind"
    )
    assert "JobKindEnum" in json.dumps(kind_parameter["schema"])
