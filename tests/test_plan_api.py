"""Tests for plan API endpoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response
from starlette.requests import Request

from osint_core.api.middleware.auth import UserInfo
from osint_core.api.routes import plan

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


def _run(awaitable):
    return asyncio.run(awaitable)


def _request(path: str, body: bytes = b"", method: str = "GET") -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive=receive,
    )


def _user() -> UserInfo:
    return UserInfo(sub="u-1", username="admin", roles=["admin"])


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
    request = _request("/api/v1/plans:validate", body=VALID_PLAN.encode(), method="POST")
    result = _run(plan.validate_plan(request))
    assert result["is_valid"] is True


def test_validate_plan_endpoint_invalid_yaml():
    request = _request("/api/v1/plans:validate", body=b"not: valid: yaml: [[", method="POST")
    result = _run(plan.validate_plan(request))
    assert result["is_valid"] is False


def test_list_active_plans():
    with patch("osint_core.api.routes.plan.store.get_all_active", AsyncMock(return_value=[_mock_plan()])):
        result = _run(plan.list_active_plans(limit=50, offset=0, db=_db(), current_user=_user()))
    assert result.items[0].plan_id == "test-plan"


def test_get_active_plan():
    with patch("osint_core.api.routes.plan.store.get_active", AsyncMock(return_value=_mock_plan())):
        result = _run(
            plan.get_active_plan(
                "test-plan",
                request=_request("/api/v1/plans/test-plan/active-version"),
                db=_db(),
                current_user=_user(),
            )
        )
    assert result.plan_id == "test-plan"


def test_update_active_plan_with_version_id():
    plan_version = _mock_plan()
    db = _db()
    with patch("osint_core.api.routes.plan.store.activate", AsyncMock(return_value=plan_version)):
        result = _run(
            plan.update_active_plan(
                "test-plan",
                body=plan.PlanActivationRequest(version_id=plan_version.id),
                request=_request("/api/v1/plans/test-plan/active-version", method="PATCH"),
                db=db,
                current_user=_user(),
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
                result = _run(
                    plan.create_plan(
                        body=plan.PlanCreateRequest(yaml=VALID_PLAN, activate=True),
                        request=_request("/api/v1/plans", method="POST"),
                        response=response,
                        db=db,
                        current_user=_user(),
                    )
                )
    assert result.id == plan_version.id
    assert response.headers["Location"].endswith(str(plan_version.id))
