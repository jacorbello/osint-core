"""Tests for ingest job submission."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Response

from osint_core.api.routes import jobs
from tests.helpers import make_request, make_user, run_async


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    return db


@patch("osint_core.api.routes.jobs.ingest_source")
def test_create_ingest_job_requires_plan_id(mock_task):
    response = run_async(
        jobs.create_job(
            body=jobs.JobCreateRequest(kind="ingest", input={"source_id": "bbc_world"}),
            request=make_request("/api/v1/jobs"),
            response=Response(),
            db=_db(),
            current_user=make_user(),
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
    job_result = run_async(
        jobs.create_job(
            body=jobs.JobCreateRequest(
                kind="ingest",
                input={"source_id": "bbc_world", "plan_id": "military-intel"},
            ),
            request=make_request("/api/v1/jobs"),
            response=response,
            db=db,
            current_user=make_user(),
        )
    )
    assert jobs.JobResponse.model_validate(job_result).kind == "ingest"
    mock_task.delay.assert_called_once_with("bbc_world", "military-intel")
