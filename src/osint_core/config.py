"""Application configuration via environment variables."""

import os

from pydantic import Field
from pydantic_settings import BaseSettings


def _deprecated_env(new_var: str, old_var: str, default: str) -> str:
    """Return *new_var* if set, else fall back to deprecated *old_var*."""
    return os.environ.get(new_var, os.environ.get(old_var, default))


class Settings(BaseSettings):
    """Global application settings.

    All values can be overridden with environment variables prefixed ``OSINT_``.
    """

    model_config = {"env_prefix": "OSINT_"}

    # --- Database ---
    database_url: str = "postgresql+asyncpg://osint:osint@postgres:5432/osint"

    # --- Redis ---
    redis_url: str = "redis://redis:6379/0"
    realtime_backend: str = "redis"
    realtime_channel_prefix: str = "osint:realtime"

    # --- Celery ---
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- Qdrant ---
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "osint-events"

    # --- LLM Provider ---
    llm_provider: str = "vllm"  # "groq" or "vllm"

    # --- vLLM (with deprecated Ollama fallbacks) ---
    vllm_url: str = Field(
        default_factory=lambda: _deprecated_env(
            "OSINT_VLLM_URL", "OSINT_OLLAMA_URL", "http://localhost:8001"
        ),
    )
    llm_model: str = Field(
        default_factory=lambda: _deprecated_env(
            "OSINT_LLM_MODEL", "OSINT_OLLAMA_MODEL", "meta-llama/Llama-3.2-3B-Instruct"
        ),
    )

    # --- Groq (cloud LLM) ---
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"

    # --- MinIO ---
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_secure: bool = False

    # --- Gotify ---
    gotify_url: str = "http://gotify/message"
    gotify_token: str = ""

    # --- SMTP (email notifications) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # --- CourtListener ---
    courtlistener_api_key: str = ""

    # --- Resend ---
    resend_api_key: str = ""
    resend_from_email: str = "reports@mail.corbello.io"
    resend_recipients: str = ""  # comma-separated list of email addresses

    # --- Shodan ---
    shodan_api_key: str = ""

    # --- Telegram ---
    telegram_bot_token: str = ""

    # --- Keycloak ---
    keycloak_url: str = "https://keycloak.corbello.io"
    keycloak_realm: str = "cortech"
    keycloak_client_id: str = "osint-core"

    # --- Auth ---
    auth_disabled: bool = True

    # --- Rate Limiting ---
    rate_limit_per_ip: int = 100
    rate_limit_per_user: int = 300
    rate_limit_trust_proxy: bool = True

    # --- OpenTelemetry ---
    otel_endpoint: str = ""
    otel_sample_rate: float = 0.1

    # --- Application ---
    plan_dir: str = "/app/plans"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=[
            "https://osint.corbello.io",
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]
    )


settings = Settings()
