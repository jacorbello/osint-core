# Pre-built base image with heavy ML dependencies.
# Build manually via: .github/workflows/build-base-images.yml
# This avoids re-installing ~4 GB of PyTorch / sentence-transformers on every CI run.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Pin versions to match pyproject.toml [project.optional-dependencies.ml]
RUN pip install --no-cache-dir \
    "sentence-transformers>=3.0.0" \
    "spacy>=3.7.0" \
    "qdrant-client>=1.9.0"

# Download default spaCy model so workers don't fetch at runtime
RUN python -m spacy download en_core_web_sm
