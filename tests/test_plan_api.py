"""Tests for plan API endpoints."""

from fastapi.testclient import TestClient

from osint_core.main import app

VALID_PLAN = """
version: 1
plan_id: test-plan
retention_class: standard
sources:
  - id: cisa_kev
    type: cisa_kev
    url: "https://example.com"
    weight: 1.0
scoring:
  recency_half_life_hours: 48
  source_reputation: {}
  ioc_match_boost: 2.0
  force_alert:
    min_severity: high
    tags_any: []
notifications:
  default_dedupe_window_minutes: 90
  routes:
    - name: test
      when:
        severity_gte: high
      channels:
        - type: gotify
          application: test
          priority: 5
"""


def test_validate_plan_endpoint():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/validate",
        content=VALID_PLAN,
        headers={"Content-Type": "application/x-yaml"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True


def test_validate_plan_endpoint_invalid_yaml():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/validate",
        content="not: valid: yaml: [[[",
        headers={"Content-Type": "application/x-yaml"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) > 0


def test_validate_plan_endpoint_missing_required():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/plan/validate",
        content="version: 1\nplan_id: incomplete\n",
        headers={"Content-Type": "application/x-yaml"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) > 0


def test_rescore_events_endpoint_no_plan_id():
    """POST /api/v1/plan/rescore enqueues a rescore task and returns task metadata."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from osint_core.main import app

    mock_task = MagicMock()
    mock_task.id = "test-task-id-1234"

    with patch(
        "osint_core.api.routes.plan.rescore_all_events_task.delay",
        return_value=mock_task,
    ) as mock_delay:
        client = TestClient(app)
        resp = client.post("/api/v1/plan/rescore")

    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "test-task-id-1234"
    assert data["status"] == "enqueued"
    assert data["plan_id"] is None
    mock_delay.assert_called_once_with(None)


def test_rescore_events_endpoint_with_plan_id():
    """POST /api/v1/plan/rescore?plan_id=foo passes plan_id to the task."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient

    from osint_core.main import app

    mock_task = MagicMock()
    mock_task.id = "test-task-id-5678"

    with patch(
        "osint_core.api.routes.plan.rescore_all_events_task.delay",
        return_value=mock_task,
    ) as mock_delay:
        client = TestClient(app)
        resp = client.post("/api/v1/plan/rescore?plan_id=my-plan")

    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "test-task-id-5678"
    assert data["status"] == "enqueued"
    assert data["plan_id"] == "my-plan"
    mock_delay.assert_called_once_with("my-plan")
