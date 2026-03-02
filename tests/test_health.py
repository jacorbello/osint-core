"""Tests for health check endpoints."""

from fastapi.testclient import TestClient

from osint_core.main import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_returns_checks():
    client = TestClient(app)
    resp = client.get("/readyz")
    # Without live services, expect 503 — but the response shape must be correct
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "postgres" in data
    assert "redis" in data
    assert "qdrant" in data


def test_readyz_reports_errors_without_services():
    """Without running postgres/redis/qdrant, all checks should report error."""
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    data = resp.json()
    assert data["postgres"] == "error"
    assert data["redis"] == "error"
    assert data["qdrant"] == "error"
