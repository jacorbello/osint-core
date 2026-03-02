# Dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY plans/ plans/
COPY schemas/ schemas/
COPY migrations/ migrations/

# FastAPI entrypoint
FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "osint_core.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Celery worker entrypoint
FROM base AS worker
CMD ["celery", "-A", "osint_core.workers.celery_app", "worker", "--loglevel=info", "-Q", "osint,ingest,enrich,score,notify"]

# Celery Beat entrypoint
FROM base AS beat
CMD ["celery", "-A", "osint_core.workers.celery_app", "beat", "--loglevel=info"]
