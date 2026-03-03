"""Tests for the ingest API route -- plan_id is required."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with auth dependency overridden."""
    from osint_core.api.deps import get_current_user
    from osint_core.api.middleware.auth import UserInfo
    from osint_core.main import app

    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        sub="test-user", username="test-user", roles=["admin"]
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@patch("osint_core.api.routes.ingest.ingest_source")
def test_run_ingest_requires_plan_id(mock_task, client):
    """POST /api/v1/ingest/source/{source_id}/run requires plan_id query param."""
    mock_task.delay.return_value = MagicMock(id="task-123")
    response = client.post(
        "/api/v1/ingest/source/bbc_world/run?plan_id=military-intel"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["plan_id"] == "military-intel"
    assert data["source_id"] == "bbc_world"
    mock_task.delay.assert_called_once_with("bbc_world", "military-intel")


@patch("osint_core.api.routes.ingest.ingest_source")
def test_run_ingest_missing_plan_id_returns_422(mock_task, client):
    """POST without plan_id should return 422."""
    response = client.post("/api/v1/ingest/source/bbc_world/run")
    assert response.status_code == 422
