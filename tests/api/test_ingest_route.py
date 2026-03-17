"""Tests for ingest job submission."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response
from starlette.requests import Request

from osint_core.api.middleware.auth import UserInfo
from osint_core.api.routes import jobs


def _run(awaitable):
    return asyncio.run(awaitable)


def _request(path: str, method: str = "POST") -> Request:
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
        }
    )


def _user() -> UserInfo:
    return UserInfo(sub="test-user", username="test-user", roles=["admin"])


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db


@patch("osint_core.api.routes.jobs.ingest_source")
def test_create_ingest_job_requires_plan_id(mock_task):
    response = _run(
        jobs.create_job(
            body=jobs.JobCreateRequest(kind="ingest", input={"source_id": "bbc_world"}),
            request=_request("/api/v1/jobs"),
            response=Response(),
            db=_db(),
            current_user=_user(),
        )
    )
    assert response.status_code == 422
    assert json.loads(response.body)["code"] == "validation_failed"
    mock_task.delay.assert_not_called()


@patch("osint_core.api.routes.jobs.ingest_source")
def test_create_ingest_job_dispatches(mock_task):
    db = _db()
    job_id = uuid.uuid4()

    async def refresh(obj):
        obj.id = job_id
        obj.job_type = "ingest"
        obj.status = "queued"
        obj.input_params = {"source_id": "bbc_world", "plan_id": "military-intel"}
        obj.output = {}
        obj.retry_count = 0
        obj.created_at = "2026-03-17T00:00:00Z"

    db.refresh = refresh
    mock_task.delay.return_value = MagicMock(id="task-123")
    response = Response()
    job_result = _run(
        jobs.create_job(
            body=jobs.JobCreateRequest(
                kind="ingest",
                input={"source_id": "bbc_world", "plan_id": "military-intel"},
            ),
            request=_request("/api/v1/jobs"),
            response=response,
            db=db,
            current_user=_user(),
        )
    )
    assert jobs.JobResponse.model_validate(job_result).kind == "ingest"
    mock_task.delay.assert_called_once_with("bbc_world", "military-intel")
