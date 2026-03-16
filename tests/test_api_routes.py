"""Tests for all API route endpoints.

Uses TestClient with mocked database sessions and auth disabled (default).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from osint_core.api.deps import get_db
from osint_core.main import app
from osint_core.models.alert import Alert
from osint_core.models.audit import AuditLog
from osint_core.models.brief import Brief
from osint_core.models.entity import Entity
from osint_core.models.event import Event
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_scalars_result(items: list, total: int = None):
    """Create mock execute results for list queries (data + count)."""
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
    """Create mock execute result for single-item queries."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = item
    return result


def _make_event(**overrides) -> MagicMock:
    """Create a mock Event for testing (avoids SQLAlchemy relationship issues)."""
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
        "search_vector": None,
        "latitude": None,
        "longitude": None,
        "country_code": None,
        "region": None,
        "source_category": None,
        "actors": None,
        "event_subtype": None,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Event)
    for k, v in defaults.items():
        setattr(mock, k, v)
    # Alias metadata_ -> metadata for Pydantic from_attributes
    mock.metadata = defaults.get("metadata_", {})
    return mock


def _make_indicator(**overrides) -> MagicMock:
    """Create a mock Indicator for testing."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "indicator_type": "ipv4",
        "value": "192.168.1.1",
        "confidence": 0.9,
        "sources": ["cisa_kev"],
        "metadata_": {},
        "first_seen": now,
        "last_seen": now,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Indicator)
    for k, v in defaults.items():
        setattr(mock, k, v)
    mock.metadata = defaults.get("metadata_", {})
    return mock


def _make_entity(**overrides) -> MagicMock:
    """Create a mock Entity for testing."""
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
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_alert(**overrides) -> MagicMock:
    """Create a mock Alert for testing."""
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
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_brief(**overrides) -> MagicMock:
    """Create a mock Brief for testing."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "title": "Test Brief",
        "content_md": "# Brief\nContent here.",
        "content_pdf_uri": None,
        "target_query": None,
        "generated_by": "template",
        "model_id": None,
        "event_ids": [],
        "entity_ids": [],
        "indicator_ids": [],
        "plan_version_id": None,
        "requested_by": None,
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=Brief)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_job(**overrides) -> MagicMock:
    """Create a mock Job for testing."""
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
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_audit_log(**overrides) -> MagicMock:
    """Create a mock AuditLog for testing."""
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "action": "event.created",
        "actor": "user-123",
        "actor_username": "testuser",
        "actor_roles": ["admin"],
        "resource_type": "event",
        "resource_id": str(uuid.uuid4()),
        "details": {},
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock(spec=AuditLog)
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEventRoutes:
    """Tests for /api/v1/events endpoints."""

    def test_list_events_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

        app.dependency_overrides.clear()

    def test_list_events_with_items(self):
        evt = _make_event()
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([evt], 1))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Test Event"

        app.dependency_overrides.clear()

    def test_list_events_pagination_params(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/events?limit=10&offset=20")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page_size"] == 10
        assert data["page"] == 3  # offset 20 / limit 10 + 1

        app.dependency_overrides.clear()

    def test_list_events_filter_params_accepted(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(
            "/api/v1/events?source_id=cisa_kev&severity=high"
            "&date_from=2026-01-01T00:00:00Z&date_to=2026-12-31T23:59:59Z"
        )
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_get_event_found(self):
        evt = _make_event()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(evt))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/events/{evt.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Event"

        app.dependency_overrides.clear()

    def test_get_event_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/events/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

class TestIndicatorRoutes:
    """Tests for /api/v1/indicators endpoints."""

    def test_list_indicators_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/indicators")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_list_indicators_with_type_filter(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/indicators?indicator_type=ipv4")
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_get_indicator_found(self):
        ind = _make_indicator()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(ind))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/indicators/{ind.id}")
        assert resp.status_code == 200
        assert resp.json()["value"] == "192.168.1.1"

        app.dependency_overrides.clear()

    def test_get_indicator_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/indicators/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

class TestEntityRoutes:
    """Tests for /api/v1/entities endpoints."""

    def test_list_entities_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/entities")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_list_entities_with_type_filter(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/entities?entity_type=organization")
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_get_entity_found(self):
        ent = _make_entity()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(ent))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/entities/{ent.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Corp"

        app.dependency_overrides.clear()

    def test_get_entity_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/entities/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class TestAlertRoutes:
    """Tests for /api/v1/alerts endpoints."""

    def test_list_alerts_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_list_alerts_with_filters(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/alerts?status=open&severity=high")
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_get_alert_found(self):
        alert = _make_alert()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(alert))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/alerts/{alert.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Alert"

        app.dependency_overrides.clear()

    def test_get_alert_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/alerts/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_ack_alert(self):
        alert = _make_alert(status="open")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(alert))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(
            f"/api/v1/alerts/{alert.id}/ack",
            json={"acked_by": "analyst1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "acked"
        assert data["acked_by"] == "analyst1"

        app.dependency_overrides.clear()

    def test_ack_alert_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(
            f"/api/v1/alerts/{uuid.uuid4()}/ack",
            json={"acked_by": "analyst1"},
        )
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_escalate_alert(self):
        alert = _make_alert(status="open")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(alert))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(
            f"/api/v1/alerts/{alert.id}/escalate",
            json={"reason": "Needs SOC review"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "escalated"

        app.dependency_overrides.clear()

    def test_resolve_alert(self):
        alert = _make_alert(status="acked")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(alert))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(f"/api/v1/alerts/{alert.id}/resolve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

class TestBriefRoutes:
    """Tests for /api/v1/briefs endpoints."""

    def test_list_briefs_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/briefs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_get_brief_found(self):
        brief = _make_brief()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(brief))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/briefs/{brief.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Brief"

        app.dependency_overrides.clear()

    def test_get_brief_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/briefs/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_generate_brief(self):
        brief_mock = _make_brief(
            title="Latest CVE threats",
            content_md="# Brief\nGenerated content.",
            target_query="Latest CVE threats",
            generated_by="llm",
            requested_by="admin",
        )

        db = _mock_db()

        # After flush, the brief should have id + created_at
        async def mock_flush():
            pass

        db.flush = mock_flush

        # Patch BriefGenerator.generate to return template content
        with patch(
            "osint_core.api.routes.briefs.BriefGenerator"
        ) as mock_gen_cls:
            mock_gen = AsyncMock()
            mock_gen.generate = AsyncMock(return_value="# Brief\nGenerated content.")
            mock_gen_cls.return_value = mock_gen

            # Patch Brief constructor to return our mock
            with patch(
                "osint_core.api.routes.briefs.Brief",
                return_value=brief_mock,
            ):
                app.dependency_overrides[get_db] = lambda: db
                client = TestClient(app)

                resp = client.post(
                    "/api/v1/briefs/generate",
                    json={"query": "Latest CVE threats"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["title"] == "Latest CVE threats"
                assert "content_md" in data

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearchRoutes:
    """Tests for /api/v1/search endpoints."""

    def test_search_events(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/search?q=ransomware")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_search_requires_query(self):
        db = _mock_db()
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/search")
        assert resp.status_code == 422  # Missing required query param

        app.dependency_overrides.clear()

    def test_semantic_search_returns_empty(self):
        client = TestClient(app)
        resp = client.get("/api/v1/search/semantic?q=ransomware")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

class TestIngestRoutes:
    """Tests for /api/v1/ingest endpoints."""

    @patch("osint_core.api.routes.ingest.ingest_source")
    def test_run_ingest(self, mock_ingest):
        mock_task = MagicMock()
        mock_task.id = "task-abc-123"
        mock_ingest.delay.return_value = mock_task

        client = TestClient(app)
        resp = client.post("/api/v1/ingest/source/cisa_kev/run?plan_id=test-plan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_id"] == "cisa_kev"
        assert data["plan_id"] == "test-plan"
        assert data["task_id"] == "task-abc-123"
        assert data["status"] == "dispatched"

        mock_ingest.delay.assert_called_once_with("cisa_kev", "test-plan")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class TestJobRoutes:
    """Tests for /api/v1/jobs endpoints."""

    def test_list_jobs_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_list_jobs_with_status_filter(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/jobs?status=running")
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_get_job_found(self):
        job = _make_job()
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(job))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/jobs/{job.id}")
        assert resp.status_code == 200
        assert resp.json()["job_type"] == "ingest"

        app.dependency_overrides.clear()

    def test_get_job_not_found(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(None))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404

        app.dependency_overrides.clear()

    def test_retry_failed_job(self):
        job = _make_job(status="failed")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(job))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(f"/api/v1/jobs/{job.id}/retry")
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        assert resp.json()["retry_count"] == 1

        app.dependency_overrides.clear()

    def test_retry_running_job_fails(self):
        job = _make_job(status="running")
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_single_result(job))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.post(f"/api/v1/jobs/{job.id}/retry")
        assert resp.status_code == 400

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestAuditRoutes:
    """Tests for /api/v1/audit endpoints."""

    def test_list_audit_empty(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/audit")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        app.dependency_overrides.clear()

    def test_list_audit_with_action_filter(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/audit?action=event.created")
        assert resp.status_code == 200

        app.dependency_overrides.clear()

    def test_list_audit_pagination(self):
        db = _mock_db()
        db.execute = AsyncMock(side_effect=_mock_scalars_result([], 0))
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        resp = client.get("/api/v1/audit?limit=10&offset=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page_size"] == 10
        assert data["page"] == 4  # offset 30 / limit 10 + 1

        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

class TestRouteRegistration:
    """Verify all routes are registered in the app."""

    def test_all_route_prefixes_registered(self):
        """All expected API prefixes should be present in the app routes."""
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        expected_prefixes = [
            "/api/v1/events",
            "/api/v1/indicators",
            "/api/v1/entities",
            "/api/v1/alerts",
            "/api/v1/briefs",
            "/api/v1/search",
            "/api/v1/ingest",
            "/api/v1/jobs",
            "/api/v1/audit",
            "/api/v1/plan",
            "/healthz",
            "/readyz",
            "/metrics",
        ]
        for prefix in expected_prefixes:
            matching = [p for p in route_paths if p.startswith(prefix)]
            assert len(matching) > 0, f"No route found for prefix: {prefix}"

    def test_openapi_schema_loads(self):
        """The OpenAPI schema should load without errors."""
        client = TestClient(app)
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "paths" in schema
        assert "/api/v1/events" in schema["paths"]
