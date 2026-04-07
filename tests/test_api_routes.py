"""Route unit tests without HTTP client transport."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response
from pydantic import ValidationError

from osint_core.api.routes import (
    alerts,
    audit,
    briefs,
    dashboard,
    entities,
    events,
    indicators,
    jobs,
    leads,
    me,
    search,
    stream,
)
from osint_core.main import app
from osint_core.models.alert import Alert
from osint_core.models.audit import AuditLog
from osint_core.models.brief import Brief
from osint_core.models.entity import Entity
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from osint_core.models.lead import Lead
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


def _mock_group_result(rows: list[tuple[str, int]]):
    result = MagicMock()
    result.all.return_value = rows
    return result


def _mock_list_result(items: list):
    scalars = MagicMock()
    scalars.all.return_value = items
    return MagicMock(scalars=MagicMock(return_value=scalars))


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
        "nlp_relevance": None,
        "nlp_summary": None,
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


def _make_lead(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "lead_type": "incident",
        "status": "new",
        "title": "Lead title",
        "summary": "Lead summary",
        "constitutional_basis": [],
        "jurisdiction": "TX",
        "institution": None,
        "severity": "medium",
        "confidence": 0.6,
        "dedupe_fingerprint": "lead-fp",
        "plan_id": "test-plan",
        "event_ids": [],
        "entity_ids": [],
        "citations": {},
        "report_id": None,
        "first_surfaced_at": now,
        "last_updated_at": now,
        "reported_at": None,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Lead)
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
    result = run_async(
        events.list_events(
            limit=10,
            offset=0,
            sort=None,
            db=db,
            current_user=make_user(),
        )
    )
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
    from osint_core.services.brief_generator import BriefContext

    brief = _make_brief(title="Latest CVE threats", target_query="Latest CVE threats")
    db = _mock_db()
    response = Response()

    fake_event = {"title": "CVE-2024-1234", "severity": "high", "score": 9.0,
                  "source_id": None, "occurred_at": None}
    fake_entity = {"name": "APT-29", "entity_type": "threat-actor"}
    fake_indicator = {"value": "10.0.0.1", "type": "ipv4"}
    mock_ctx = BriefContext(
        events=[fake_event],
        entities=[fake_entity],
        indicators=[fake_indicator],
        event_ids=[uuid.uuid4()],
        entity_ids=[uuid.uuid4()],
        indicator_ids=[uuid.uuid4()],
    )
    with (
        patch(
            "osint_core.api.routes.briefs.fetch_brief_context",
            new_callable=AsyncMock,
            return_value=mock_ctx,
        ),
        patch("osint_core.api.routes.briefs.BriefGenerator") as generator_cls,
        patch("osint_core.api.routes.briefs.Brief", return_value=brief),
    ):
        generator = AsyncMock()
        generator.generate = AsyncMock(return_value=("# Brief\nGenerated content.", "vllm"))
        generator_cls.return_value = generator
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
    generator.generate.assert_awaited_once_with(
        query="Latest CVE threats",
        events=[fake_event],
        indicators=[fake_indicator],
        entities=[fake_entity],
    )


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


def test_get_me_reflects_current_user_and_auth_mode():
    with patch("osint_core.api.routes.me.settings") as mock_settings:
        mock_settings.auth_disabled = True
        result = run_async(me.get_me(current_user=make_user()))
    assert result.username == "admin"
    assert result.auth_disabled is True


def test_get_dashboard_summary_returns_zero_filled_statuses():
    db = _mock_db()
    db.execute = AsyncMock(
        side_effect=[
            _mock_group_result([("open", 3)]),
            _mock_group_result([("active", 2)]),
            _mock_group_result([("new", 4), ("qualified", 1)]),
            _mock_group_result([("queued", 9)]),
            MagicMock(scalar_one=MagicMock(return_value=17)),
        ]
    )
    result = run_async(dashboard.get_dashboard_summary(db=db, current_user=make_user()))
    assert result.alerts["open"] == 3
    assert result.alerts["resolved"] == 0
    assert result.watches["active"] == 2
    assert result.leads["new"] == 4
    assert result.leads["reviewing"] == 0
    assert result.jobs["queued"] == 9
    assert result.events.last_24h_count == 17


def test_list_event_facets_returns_buckets():
    db = _mock_db()
    db.execute = AsyncMock(
        side_effect=[
            _mock_group_result([("high", 10), ("medium", 3)]),
            _mock_group_result([("cisa_kev", 8), ("otx", 5)]),
            _mock_group_result([("cyber", 7)]),
            _mock_group_result([("US", 6), ("CA", 2)]),
        ]
    )
    result = run_async(
        events.list_event_facets(
            source_id=None,
            severity=None,
            date_from=None,
            date_to=None,
            attack_technique=None,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.facets["severity"][0].value == "high"
    assert result.facets["source_id"][1].value == "otx"
    assert result.facets["country_code"][0].count == 6


def test_list_alert_facets_returns_buckets():
    db = _mock_db()
    db.execute = AsyncMock(
        side_effect=[
            _mock_group_result([("open", 2), ("acked", 1)]),
            _mock_group_result([("critical", 2)]),
            _mock_group_result([("pager", 2)]),
        ]
    )
    result = run_async(
        alerts.list_alert_facets(
            status=None,
            severity=None,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.facets["status"][0].value == "open"
    assert result.facets["severity"][0].count == 2
    assert result.facets["route_name"][0].value == "pager"


def test_list_lead_facets_returns_buckets():
    db = _mock_db()
    db.execute = AsyncMock(
        side_effect=[
            _mock_group_result([("new", 5), ("reviewing", 1)]),
            _mock_group_result([("incident", 6)]),
            _mock_group_result([("TX", 4)]),
            _mock_group_result([("cyber-threat-intel", 6)]),
        ]
    )
    result = run_async(
        leads.list_lead_facets(
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.facets["status"][0].value == "new"
    assert result.facets["lead_type"][0].value == "incident"
    assert result.facets["plan_id"][0].count == 6


def test_bulk_update_alerts_mixed_outcomes():
    alert_open = _make_alert(status="open")
    alert_acked = _make_alert(status="acked")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([alert_open, alert_acked]))
    body = alerts.AlertBulkUpdateRequest(
        ids=[alert_open.id, alert_acked.id, uuid.uuid4()],
        target_status="resolved",
        dry_run=False,
    )
    result = run_async(alerts.bulk_update_alerts(body=body, db=db, current_user=make_user()))
    assert result.summary.updated == 1
    assert result.summary.skipped == 2
    assert any(item.reason_code == "invalid_transition" for item in result.skipped)
    assert any(item.reason_code == "not_found" for item in result.skipped)


def test_bulk_update_alerts_dry_run_does_not_commit_or_publish():
    alert_open = _make_alert(status="open")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([alert_open]))
    with patch(
        "osint_core.api.routes.alerts.publish_event",
        new_callable=AsyncMock,
    ) as publish_mock:
        result = run_async(
            alerts.bulk_update_alerts(
                body=alerts.AlertBulkUpdateRequest(
                    ids=[alert_open.id],
                    target_status="acked",
                    dry_run=True,
                ),
                db=db,
                current_user=make_user(),
            )
        )
    assert result.summary.updated == 1
    db.commit.assert_not_awaited()
    publish_mock.assert_not_awaited()


def test_bulk_update_leads_respects_transition_rules():
    lead_new = _make_lead(status="new")
    lead_reviewing = _make_lead(status="reviewing")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([lead_new, lead_reviewing]))
    body = leads.LeadBulkUpdateRequest(
        ids=[lead_new.id, lead_reviewing.id],
        target_status="qualified",
        dry_run=False,
    )
    result = run_async(leads.bulk_update_leads(body=body, db=db, current_user=make_user()))
    assert result.summary.updated == 1
    assert result.summary.skipped == 1
    assert result.updated[0].id == lead_reviewing.id


def test_bulk_update_leads_dry_run_does_not_commit_or_publish():
    lead_new = _make_lead(status="new")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([lead_new]))
    with patch(
        "osint_core.api.routes.leads.publish_event",
        new_callable=AsyncMock,
    ) as publish_mock:
        result = run_async(
            leads.bulk_update_leads(
                body=leads.LeadBulkUpdateRequest(
                    ids=[lead_new.id],
                    target_status="reviewing",
                    dry_run=True,
                ),
                db=db,
                current_user=make_user(),
            )
        )
    assert result.summary.updated == 1
    db.commit.assert_not_awaited()
    publish_mock.assert_not_awaited()


def test_bulk_request_rejects_more_than_1000_ids():
    too_many = [uuid.uuid4() for _ in range(1001)]
    with pytest.raises(ValidationError):
        alerts.AlertBulkUpdateRequest(ids=too_many, target_status="acked")


def test_export_alerts_csv_response():
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([_make_alert()]))
    response = run_async(
        alerts.export_alerts(
            format="csv",
            status=None,
            severity=None,
            limit=1000,
            db=db,
            current_user=make_user(),
        )
    )
    assert response.media_type == "text/csv"
    assert "fingerprint" in response.body.decode()


def test_export_events_json_response():
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_list_result([_make_event()]))
    response = run_async(
        events.export_events(
            format="json",
            source_id=None,
            severity=None,
            date_from=None,
            date_to=None,
            attack_technique=None,
            sort=None,
            limit=1000,
            db=db,
            current_user=make_user(),
        )
    )
    payload = json.loads(response.body)
    assert isinstance(payload, list)
    assert payload[0]["event_type"] == "vulnerability"


def test_get_event_related_returns_joined_sections():
    event = _make_event()
    related_alert = _make_alert(event_ids=[event.id])
    related_entity = _make_entity()
    related_indicator = _make_indicator()
    db = _mock_db()
    db.execute = AsyncMock(
        side_effect=[
            _mock_single_result(event),
            _mock_list_result([related_alert]),
            _mock_list_result([related_entity]),
            _mock_list_result([related_indicator]),
        ]
    )
    result = run_async(
        events.get_event_related(
            event_id=event.id,
            request=make_request(f"/api/v1/events/{event.id}/related"),
            include=None,
            db=db,
            current_user=make_user(),
        )
    )
    assert result.meta.alert_count == 1
    assert result.meta.entity_count == 1
    assert result.meta.indicator_count == 1


def test_get_event_related_rejects_unknown_include():
    db = _mock_db()
    response = run_async(
        events.get_event_related(
            event_id=uuid.uuid4(),
            request=make_request("/api/v1/events/x/related"),
            include="alerts,foo",
            db=db,
            current_user=make_user(),
        )
    )
    assert response.status_code == 422
    assert json.loads(response.body)["code"] == "validation_failed"


def test_stream_updates_returns_sse_response():
    response = run_async(stream.stream_updates(current_user=make_user()))
    assert response.media_type == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"


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
    with patch(
        "osint_core.api.routes.audit.list_audit_entries",
        AsyncMock(return_value=([_make_audit()], 1)),
    ):
        result = run_async(
            audit.list_audit(
                limit=10,
                offset=0,
                action=None,
                db=_mock_db(),
                current_user=make_user(),
            )
        )
    assert result.page.total == 1


def test_get_brief_pdf_returns_pdf_response():
    brief = _make_brief(content_md="# Test\n\nPDF content", title="PDF Brief")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(brief))

    fake_pdf = b"%PDF-1.4 test content"
    with (
        patch(
            "osint_core.services.pdf_export.render_brief_pdf",
            return_value=fake_pdf,
        ),
        patch(
            "osint_core.services.pdf_export.generate_and_upload_pdf",
            return_value="minio://osint-briefs/briefs/test.pdf",
        ),
    ):
        result = run_async(
            briefs.get_brief_pdf(
                brief_id=brief.id,
                request=make_request(f"/api/v1/briefs/{brief.id}/pdf"),
                db=db,
                current_user=make_user(),
            )
        )

    assert result.status_code == 200
    assert result.media_type == "application/pdf"
    assert result.body == fake_pdf
    assert "Content-Disposition" in result.headers


def test_get_brief_pdf_returns_404_for_missing_brief():
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(None))

    result = run_async(
        briefs.get_brief_pdf(
            brief_id=uuid.uuid4(),
            request=make_request("/api/v1/briefs/missing/pdf"),
            db=db,
            current_user=make_user(),
        )
    )

    assert result.status_code == 404
    assert json.loads(result.body)["code"] == "not_found"


def test_get_brief_pdf_returns_503_on_render_failure():
    brief = _make_brief(content_md="# Test")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(brief))

    with patch(
        "osint_core.services.pdf_export.render_brief_pdf",
        side_effect=RuntimeError("weasyprint failed"),
    ):
        result = run_async(
            briefs.get_brief_pdf(
                brief_id=brief.id,
                request=make_request(f"/api/v1/briefs/{brief.id}/pdf"),
                db=db,
                current_user=make_user(),
            )
        )

    assert result.status_code == 503
    assert json.loads(result.body)["code"] == "pdf_render_failed"


def test_get_brief_pdf_still_returns_pdf_when_minio_fails():
    brief = _make_brief(content_md="# Test", title="Fallback Brief")
    db = _mock_db()
    db.execute = AsyncMock(return_value=_mock_single_result(brief))

    fake_pdf = b"%PDF-1.4 fallback"
    with (
        patch(
            "osint_core.services.pdf_export.render_brief_pdf",
            return_value=fake_pdf,
        ),
        patch(
            "osint_core.services.pdf_export.generate_and_upload_pdf",
            side_effect=ConnectionError("MinIO down"),
        ),
    ):
        result = run_async(
            briefs.get_brief_pdf(
                brief_id=brief.id,
                request=make_request(f"/api/v1/briefs/{brief.id}/pdf"),
                db=db,
                current_user=make_user(),
            )
        )

    # Should still return the PDF even though MinIO upload failed.
    assert result.status_code == 200
    assert result.body == fake_pdf


def test_openapi_schema_loads():
    schema = app.openapi()
    assert "/api/v1/jobs" in schema["paths"]
    assert "/api/v1/me" in schema["paths"]
    assert "/api/v1/dashboard/summary" in schema["paths"]
    assert "/api/v1/events/facets" in schema["paths"]
    assert "/api/v1/events/export" in schema["paths"]
    assert "/api/v1/events/{event_id}/related" in schema["paths"]
    assert "/api/v1/alerts/facets" in schema["paths"]
    assert "/api/v1/alerts/export" in schema["paths"]
    assert "/api/v1/alerts/bulk-update" in schema["paths"]
    assert "/api/v1/leads/facets" in schema["paths"]
    assert "/api/v1/leads/export" in schema["paths"]
    assert "/api/v1/leads/bulk-update" in schema["paths"]
    assert "/api/v1/stream" in schema["paths"]
    assert "/api/v1/plans" in schema["paths"]
    assert "/api/v1/briefs/{brief_id}/pdf" in schema["paths"]
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
