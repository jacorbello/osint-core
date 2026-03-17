"""Tests for plan API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response

from osint_core.api.routes import plan
from tests.helpers import make_request, make_user, run_async

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


def _mock_plan(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "plan_id": "test-plan",
        "version": 1,
        "content_hash": "sha256:123",
        "content": {"plan_id": "test-plan"},
        "retention_class": "standard",
        "git_commit_sha": None,
        "activated_at": now,
        "activated_by": "admin",
        "is_active": True,
        "validation_result": {"is_valid": True},
        "created_at": now,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for key, value in defaults.items():
        setattr(mock, key, value)
    return mock


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def test_validate_plan_endpoint():
    request = make_request("/api/v1/plans:validate", body=VALID_PLAN.encode(), method="POST")
    result = run_async(plan.validate_plan(request))
    assert result["is_valid"] is True


def test_validate_plan_endpoint_invalid_yaml():
    request = make_request("/api/v1/plans:validate", body=b"not: valid: yaml: [[", method="POST")
    result = run_async(plan.validate_plan(request))
    assert result["is_valid"] is False


def test_list_active_plans():
    with patch("osint_core.api.routes.plan.store.list_active", AsyncMock(return_value=([_mock_plan()], 1))):
        result = run_async(plan.list_active_plans(limit=50, offset=0, db=_db(), current_user=make_user()))
    assert result.items[0].plan_id == "test-plan"
    assert result.page.total == 1


def test_list_plan_versions_uses_store_total():
    with patch("osint_core.api.routes.plan.store.list_versions", AsyncMock(return_value=([_mock_plan()], 7))):
        result = run_async(
            plan.list_plan_versions(
                "test-plan",
                limit=2,
                offset=4,
                db=_db(),
                current_user=make_user(),
            )
        )
    assert result.items[0].plan_id == "test-plan"
    assert result.page.total == 7
    assert result.page.has_more is True


def test_get_active_plan():
    with patch("osint_core.api.routes.plan.store.get_active", AsyncMock(return_value=_mock_plan())):
        result = run_async(
            plan.get_active_plan(
                "test-plan",
                request=make_request("/api/v1/plans/test-plan/active-version"),
                db=_db(),
                current_user=make_user(),
            )
        )
    assert result.plan_id == "test-plan"


def test_update_active_plan_with_version_id():
    plan_version = _mock_plan()
    db = _db()
    with patch("osint_core.api.routes.plan.store.activate", AsyncMock(return_value=plan_version)):
        result = run_async(
            plan.update_active_plan(
                "test-plan",
                body=plan.PlanActivationRequest(version_id=plan_version.id),
                request=make_request("/api/v1/plans/test-plan/active-version", method="PATCH"),
                db=db,
                current_user=make_user(),
            )
        )
    assert result.id == plan_version.id


def test_get_plan_version_uses_direct_lookup():
    plan_version = _mock_plan()
    with patch("osint_core.api.routes.plan.store.get_version", AsyncMock(return_value=plan_version)):
        result = run_async(
            plan.get_plan_version(
                "test-plan",
                plan_version.id,
                request=make_request(f"/api/v1/plans/test-plan/versions/{plan_version.id}"),
                db=_db(),
                current_user=make_user(),
            )
        )
    assert result.id == plan_version.id


def test_create_plan_version():
    db = _db()
    response = Response()
    plan_version = _mock_plan()
    with patch("osint_core.api.routes.plan.store.get_next_version", AsyncMock(return_value=1)):
        with patch("osint_core.api.routes.plan.store.store_version", AsyncMock(return_value=plan_version)):
            with patch("osint_core.api.routes.plan.store.activate", AsyncMock(return_value=plan_version)):
                result = run_async(
                    plan.create_plan(
                        body=plan.PlanCreateRequest(yaml=VALID_PLAN, activate=True),
                        request=make_request("/api/v1/plans", method="POST"),
                        response=response,
                        db=db,
                        current_user=make_user(),
                    )
                )
    assert result.id == plan_version.id
    assert response.headers["Location"].endswith(str(plan_version.id))
