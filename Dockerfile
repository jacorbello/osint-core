# Dockerfile
# Uses pre-built base with ML deps (sentence-transformers, spaCy, qdrant-client).
# Rebuild base via: .github/workflows/build-base-images.yml
FROM harbor.corbello.io/osint/python-base:ml-latest AS base
WORKDIR /app

# Install only core Python deps (ML deps already in base image)
COPY pyproject.toml .
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "."

COPY alembic.ini .
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
