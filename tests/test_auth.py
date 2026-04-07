"""Tests for Keycloak OIDC JWT authentication middleware."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from osint_core.api.middleware.auth import (
    _DEFAULT_ADMIN,
    UserInfo,
    get_current_user,
    require_role,
)
from osint_core.config import Settings

# ---- Helper: build a mini app with a protected route for testing ----

def _make_app(auth_disabled: bool = True) -> FastAPI:
    """Create a small FastAPI app with a protected endpoint."""
    app = FastAPI()

    @app.get("/api/v1/events")
    async def list_events(user: UserInfo = Depends(get_current_user)):
        return {"user": user.username}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics():
        return {"metrics": "ok"}

    @app.get("/admin-only")
    async def admin_only(user: UserInfo = Depends(require_role("admin"))):
        return {"user": user.username, "roles": user.roles}

    return app


# ---- Tests with auth DISABLED (default dev/test mode) ----

def test_valid_token_passes_when_auth_disabled():
    """When auth_disabled=True, any request gets the default admin user."""
    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = True
        app = _make_app(auth_disabled=True)
        client = TestClient(app)
        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        assert resp.json()["user"] == "admin"


def test_health_endpoints_exempt():
    """/healthz, /readyz, /metrics don't require auth (no Depends(get_current_user))."""
    app = _make_app()
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/metrics").status_code == 200


# ---- Tests with auth ENABLED ----

def test_protected_endpoint_rejects_no_token():
    """GET /api/v1/events without token returns 401 when auth is enabled."""
    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = False
        app = _make_app(auth_disabled=False)
        client = TestClient(app)
        resp = client.get("/api/v1/events")
        assert resp.status_code == 401


def test_protected_endpoint_rejects_invalid_token():
    """Invalid Bearer token returns 401 when auth is enabled."""
    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = False
        mock_settings.keycloak_url = "http://localhost:8080"
        mock_settings.keycloak_realm = "test"
        mock_settings.keycloak_client_id = "test-client"

        app = _make_app(auth_disabled=False)
        client = TestClient(app)
        resp = client.get(
            "/api/v1/events",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )
        assert resp.status_code == 401


def test_valid_token_passes():
    """A mocked valid JWT passes through and returns user info."""
    mock_user = UserInfo(sub="user-123", username="testuser", roles=["analyst"])

    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = False

        # We patch get_current_user at the app level to simulate valid token
        app = _make_app(auth_disabled=False)

        # Override the dependency
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)

        resp = client.get("/api/v1/events")
        assert resp.status_code == 200
        assert resp.json()["user"] == "testuser"

        app.dependency_overrides.clear()


# ---- UserInfo model tests ----

def test_user_info_model():
    """UserInfo should hold sub, username, and roles."""
    user = UserInfo(sub="abc-123", username="analyst1", roles=["analyst", "viewer"])
    assert user.sub == "abc-123"
    assert user.username == "analyst1"
    assert user.roles == ["analyst", "viewer"]


def test_user_info_defaults():
    """UserInfo roles defaults to empty list."""
    user = UserInfo(sub="abc-123", username="user")
    assert user.roles == []


def test_default_admin_user():
    """The default admin user used in dev mode is configured correctly."""
    assert _DEFAULT_ADMIN.sub == "dev-admin"
    assert _DEFAULT_ADMIN.username == "admin"
    assert "admin" in _DEFAULT_ADMIN.roles


# ---- require_role tests ----

def test_require_role_passes_with_correct_role():
    """require_role should pass when user has the required role."""
    mock_user = UserInfo(sub="u1", username="admin", roles=["admin", "analyst"])

    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = False

        app = _make_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)

        resp = client.get("/admin-only")
        assert resp.status_code == 200
        assert resp.json()["user"] == "admin"

        app.dependency_overrides.clear()


def test_require_role_rejects_missing_role():
    """require_role should return 403 when user lacks the required role."""
    mock_user = UserInfo(sub="u2", username="viewer", roles=["viewer"])

    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = False

        app = _make_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user
        client = TestClient(app)

        resp = client.get("/admin-only")
        assert resp.status_code == 403

        app.dependency_overrides.clear()


def test_require_role_passes_when_auth_disabled():
    """require_role should pass when auth is disabled."""
    with patch("osint_core.api.middleware.auth.settings") as mock_settings:
        mock_settings.auth_disabled = True

        app = _make_app()
        client = TestClient(app)

        resp = client.get("/admin-only")
        assert resp.status_code == 200

        app.dependency_overrides.clear()


# ---- Settings integration ----

def test_auth_disabled_in_settings():
    """Settings should have auth_disabled field defaulting to True."""
    s = Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/1",
        celery_result_backend="redis://localhost:6379/2",
    )
    assert s.auth_disabled is True


def test_auth_enabled_in_settings():
    """auth_disabled can be set to False."""
    s = Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/1",
        celery_result_backend="redis://localhost:6379/2",
        auth_disabled=False,
    )
    assert s.auth_disabled is False

