"""Shared test fixtures for osint-core."""

import pytest

from osint_core.config import Settings


@pytest.fixture()
def settings() -> Settings:
  """Return a Settings instance with test-friendly defaults."""
  return Settings(
    database_url="postgresql+asyncpg://test:test@localhost:5432/osint_test",
    redis_url="redis://localhost:6379/0",
    celery_broker_url="redis://localhost:6379/1",
    celery_result_backend="redis://localhost:6379/2",
    qdrant_host="localhost",
    minio_endpoint="localhost:9000",
    gotify_url="http://localhost/message",
    keycloak_url="http://localhost:8080",
    plan_dir="/tmp/osint-plans",
  )
