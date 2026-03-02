"""Application configuration via environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
  """Global application settings.

  All values can be overridden with environment variables prefixed ``OSINT_``.
  """

  model_config = {"env_prefix": "OSINT_"}

  # --- Database ---
  database_url: str = "postgresql+asyncpg://osint:osint@postgres:5432/osint"

  # --- Redis ---
  redis_url: str = "redis://redis:6379/0"

  # --- Celery ---
  celery_broker_url: str = "redis://redis:6379/1"
  celery_result_backend: str = "redis://redis:6379/2"

  # --- Qdrant ---
  qdrant_host: str = "qdrant"
  qdrant_port: int = 6333
  qdrant_collection: str = "osint-events"

  # --- Ollama ---
  ollama_url: str = "http://ollama:11434"
  ollama_model: str = "llama3.1:8b"

  # --- MinIO ---
  minio_endpoint: str = "minio:9000"
  minio_access_key: str = ""
  minio_secret_key: str = ""
  minio_secure: bool = False

  # --- Gotify ---
  gotify_url: str = "http://gotify/message"
  gotify_token: str = ""

  # --- Keycloak ---
  keycloak_url: str = "https://keycloak.corbello.io"
  keycloak_realm: str = "cortech"
  keycloak_client_id: str = "osint-core"

  # --- Application ---
  plan_dir: str = "/app/plans"
  log_level: str = "INFO"
  api_prefix: str = "/api/v1"
  cors_origins: list[str] = Field(default=["*"])


settings = Settings()
