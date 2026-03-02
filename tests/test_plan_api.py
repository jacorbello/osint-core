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
