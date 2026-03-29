# Configuration Reference

Core application configuration is managed through environment variables prefixed with `OSINT_`.
This page documents the `OSINT_` variables that are loaded by `src/osint_core/config.py` using
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/). Other components may read additional `OSINT_` environment variables directly; refer to their module documentation for details.

## Environment Variables

### Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_DATABASE_URL` | No | `postgresql+asyncpg://osint:osint@postgres:5432/osint` | Async PostgreSQL connection string. Must use the `postgresql+asyncpg://` driver. |

### Redis

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_REDIS_URL` | No | `redis://redis:6379/0` | Redis URL for general caching and pub/sub. |

### Celery

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_CELERY_BROKER_URL` | No | `redis://redis:6379/1` | Celery broker URL (typically a separate Redis DB). |
| `OSINT_CELERY_RESULT_BACKEND` | No | `redis://redis:6379/2` | Celery result backend URL. |

### Qdrant (Vector Store)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_QDRANT_HOST` | No | `qdrant` | Qdrant server hostname. |
| `OSINT_QDRANT_PORT` | No | `6333` | Qdrant server port. |
| `OSINT_QDRANT_COLLECTION` | No | `osint-events` | Qdrant collection name for event embeddings. |

### LLM (vLLM)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_VLLM_URL` | No | `http://localhost:8001` | vLLM inference server URL. Falls back to deprecated `OSINT_OLLAMA_URL` if set. |
| `OSINT_LLM_MODEL` | No | `meta-llama/Llama-3.2-3B-Instruct` | LLM model identifier. Falls back to deprecated `OSINT_OLLAMA_MODEL` if set. |
| `OSINT_OLLAMA_URL` | No | `""` | Deprecated. Legacy inference server URL used only for backward compatibility. Prefer `OSINT_VLLM_URL`. |
| `OSINT_OLLAMA_MODEL` | No | `""` | Deprecated. Legacy model identifier used only for backward compatibility. Prefer `OSINT_LLM_MODEL`. |

### MinIO (Object Storage)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_MINIO_ENDPOINT` | No | `minio:9000` | MinIO server endpoint (host:port). |
| `OSINT_MINIO_ACCESS_KEY` | Yes* | `""` | MinIO access key. Required for object storage operations. |
| `OSINT_MINIO_SECRET_KEY` | Yes* | `""` | MinIO secret key. Required for object storage operations. |
| `OSINT_MINIO_SECURE` | No | `false` | Use HTTPS for MinIO connections. |

### Gotify & Notifications (Push Notifications)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_GOTIFY_URL` | No | `http://gotify/message` | Gotify message endpoint URL. |
| `OSINT_GOTIFY_TOKEN` | Yes* | `""` | Gotify application token. Required for push notifications. |
| `OSINT_NOTIFY_THRESHOLD` | No | `medium` | Minimum event severity required to send notifications (for example: `low`, `medium`, `high`). |
| `OSINT_SLACK_WEBHOOK_URL` | No | `""` | Slack Incoming Webhook URL. When set, enables Slack notifications. |

### SMTP (Email Notifications)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_SMTP_HOST` | Yes* | `""` | SMTP server hostname. Required for legacy email delivery. |
| `OSINT_SMTP_PORT` | No | `587` | SMTP server port. |
| `OSINT_SMTP_USER` | Yes* | `""` | SMTP authentication username. |
| `OSINT_SMTP_PASSWORD` | Yes* | `""` | SMTP authentication password. |
| `OSINT_SMTP_FROM` | Yes* | `""` | Sender address for SMTP emails. |

### CourtListener

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_COURTLISTENER_API_KEY` | Yes* | `""` | API key for the [CourtListener](https://www.courtlistener.com/) citation verification service. Required for legal citation lookups in prospecting reports. Store in Infisical under `cortech-infra/prod`. |

### Resend (Email Delivery)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_RESEND_API_KEY` | Yes* | `""` | API key for the [Resend](https://resend.com/) transactional email service. Required for sending prospecting reports via email. Store in Infisical under `cortech-infra/prod`. |
| `OSINT_RESEND_FROM_EMAIL` | No | `reports@corbello.io` | Sender email address used for prospecting report delivery. Must be a verified domain in Resend. |
| `OSINT_RESEND_RECIPIENTS` | No | `""` | Comma-separated list of default recipient email addresses for prospecting report emails. |

### Shodan

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_SHODAN_API_KEY` | Yes* | `""` | Shodan API key for network reconnaissance queries. |

### Telegram

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_TELEGRAM_BOT_TOKEN` | Yes* | `""` | Telegram bot token for channel notifications. |

### Keycloak (Authentication)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_KEYCLOAK_URL` | No | `https://keycloak.corbello.io` | Keycloak server URL. |
| `OSINT_KEYCLOAK_REALM` | No | `cortech` | Keycloak realm name. |
| `OSINT_KEYCLOAK_CLIENT_ID` | No | `osint-core` | Keycloak client ID for OIDC authentication. |

### Auth

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_AUTH_DISABLED` | No | `true` | Disable authentication checks. Set to `false` in production. |

### Rate Limiting

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_RATE_LIMIT_PER_IP` | No | `100` | Maximum requests per IP per window. |
| `OSINT_RATE_LIMIT_PER_USER` | No | `300` | Maximum requests per authenticated user per window. |
| `OSINT_RATE_LIMIT_TRUST_PROXY` | No | `true` | Trust `X-Forwarded-For` header for client IP detection. |

### OpenTelemetry

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_OTEL_ENDPOINT` | No | `""` | OTLP exporter endpoint. Leave empty to disable tracing. |
| `OSINT_OTEL_SAMPLE_RATE` | No | `0.1` | Trace sampling rate (0.0 to 1.0). |

### Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OSINT_PLAN_DIR` | No | `/app/plans` | Directory containing YAML prospecting plan files. |
| `OSINT_LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `OSINT_API_PREFIX` | No | `/api/v1` | URL prefix for all API routes. |
| `OSINT_CORS_ORIGINS` | No | `["*"]` | Allowed CORS origins (JSON array). |

> **Yes*** — Required when using the associated feature. The application starts without
> these values, but the relevant functionality will fail at runtime.

## Secrets Management

API keys and credentials should be stored in **Infisical** under the
`cortech-infra/prod` environment rather than committed to source control or
passed as plain-text environment variables in deployment manifests.

The following variables are examples of secrets and should be managed through Infisical (non-exhaustive):

- `OSINT_DATABASE_URL` (contains credentials)
- `OSINT_MINIO_ACCESS_KEY` / `OSINT_MINIO_SECRET_KEY`
- `OSINT_GOTIFY_TOKEN`
- `OSINT_SMTP_USER`
- `OSINT_SMTP_PASSWORD`
- `OSINT_COURTLISTENER_API_KEY`
- `OSINT_RESEND_API_KEY`
- `OSINT_SHODAN_API_KEY`
- `OSINT_TELEGRAM_BOT_TOKEN`
- `OSINT_SLACK_WEBHOOK_URL`
